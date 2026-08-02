// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Per-topic mastery, read from FSRS memory state.
//!
//! This replaces the two numbers Anki already shows and that neither means what
//! students think. "Mature cards" counts cards the scheduler decided to wait 21
//! days on — a setting, not knowledge. "Estimated total knowledge" is card
//! count times recall probability, so adding three thousand junk cards makes it
//! go up. Neither is anchored to what the exam actually asks about.

use std::collections::HashMap;

use anki_proto::speedrun::TopicMastery;
use anki_proto::speedrun::TopicMasteryRequest;
use anki_proto::speedrun::TopicMasteryResponse;
use fsrs::FSRS5_DEFAULT_DECAY;

use crate::prelude::*;
use crate::search::SortMode;
use crate::speedrun::thresholds::ATTEMPT_NOTETYPE;
use crate::speedrun::thresholds::DEFAULT_TAG_PREFIX;
use crate::speedrun::topic_from_tags;

/// Running totals for one topic. Kept in f64 so that summing tens of thousands
/// of f32 probabilities doesn't drift.
#[derive(Default)]
struct Accumulator {
    section: String,
    sum_r: f64,
    sum_r_squared: f64,
    with_memory_state: u32,
    cards: u32,
    reviews: u32,
}

impl Accumulator {
    /// Mean retrievability with a normal-approximation 95% interval.
    ///
    /// The interval describes uncertainty about the topic mean from a finite
    /// number of cards. It says nothing about whether the card→topic mapping is
    /// right; that error is measured separately and reported alongside.
    fn mean_and_range(&self) -> (f32, f32, f32) {
        let n = self.with_memory_state as f64;
        if n == 0.0 {
            return (0.0, 0.0, 0.0);
        }
        let mean = self.sum_r / n;
        if n < 2.0 {
            return (mean as f32, 0.0, 1.0);
        }
        let variance = (self.sum_r_squared / n - mean * mean).max(0.0);
        let std_error = (variance / n).sqrt();
        let low = (mean - 1.96 * std_error).clamp(0.0, 1.0);
        let high = (mean + 1.96 * std_error).clamp(0.0, 1.0);
        (mean as f32, low as f32, high as f32)
    }
}

/// Search matching the cards we are willing to measure.
///
/// The negated notetype clause is the contamination guard: Speedrun's own
/// attempt cards must never reach a mastery number.
fn measurable_cards_search(section: &str, tag_prefix: &str) -> String {
    let prefix = if tag_prefix.is_empty() {
        DEFAULT_TAG_PREFIX
    } else {
        tag_prefix
    };
    let tag = if section.is_empty() {
        format!("{prefix}::*")
    } else {
        format!("{prefix}::{section}::*")
    };
    format!("\"tag:{tag}\" -\"note:{ATTEMPT_NOTETYPE}\"")
}

impl Collection {
    pub(crate) fn speedrun_topic_mastery(
        &mut self,
        req: TopicMasteryRequest,
    ) -> Result<TopicMasteryResponse> {
        let prefix = if req.tag_prefix.is_empty() {
            DEFAULT_TAG_PREFIX.to_string()
        } else {
            req.tag_prefix.clone()
        };
        let search = measurable_cards_search(&req.section, &prefix);

        // Borrowed before the search guards, which hold &mut self.
        let timing = self.timing_today()?;

        let cards = {
            let guard = self.search_cards_into_table(search.as_str(), SortMode::NoOrder)?;
            guard.col.storage.all_searched_cards()?
        };
        let tags_by_note: HashMap<NoteId, Vec<String>> = {
            let guard = self.search_notes_into_table(search.as_str())?;
            guard
                .col
                .storage
                .all_searched_notes()?
                .into_iter()
                .map(|note| (note.id, note.tags))
                .collect()
        };
        let cards_excluded = self.speedrun_excluded_card_count()?;

        let mut topics: HashMap<String, Accumulator> = HashMap::new();
        let mut cards_considered = 0u32;

        for card in &cards {
            let Some(tags) = tags_by_note.get(&card.note_id) else {
                continue;
            };
            let Some(topic) = topic_from_tags(tags, &prefix) else {
                continue;
            };
            cards_considered += 1;

            let entry = topics.entry(topic.id.to_string()).or_default();
            if entry.section.is_empty() {
                entry.section = topic.section.to_string();
            }
            entry.cards += 1;
            entry.reviews += card.reps;

            // A card FSRS has no memory state for cannot contribute a
            // probability. We count it toward coverage and leave it out of the
            // mean rather than inventing a value for it.
            if let Some(state) = card.memory_state {
                let elapsed_days = card
                    .seconds_since_last_review(&timing)
                    .unwrap_or_default() as f32
                    / 86_400.0;
                let r = fsrs::current_retrievability(
                    state.into(),
                    elapsed_days,
                    card.decay.unwrap_or(FSRS5_DEFAULT_DECAY),
                );
                entry.sum_r += r as f64;
                entry.sum_r_squared += (r as f64) * (r as f64);
                entry.with_memory_state += 1;
            }
        }

        let mut out: Vec<TopicMastery> = topics
            .into_iter()
            .map(|(topic_id, acc)| {
                let (mean, low, high) = acc.mean_and_range();
                TopicMastery {
                    topic_id,
                    section: acc.section,
                    mean_retrievability: mean,
                    range_low: low,
                    range_high: high,
                    card_count: acc.cards,
                    cards_with_memory_state: acc.with_memory_state,
                    review_count: acc.reviews,
                    // A topic with cards but no graded history is not covered.
                    // Owning cards about something is not the same as having
                    // studied it.
                    covered: acc.reviews > 0,
                }
            })
            .collect();
        out.sort_by(|a, b| a.topic_id.cmp(&b.topic_id));

        Ok(TopicMasteryResponse {
            topics: out,
            cards_considered,
            cards_excluded,
        })
    }

    /// How many of Speedrun's own cards were kept out of the measurement.
    ///
    /// Reported rather than silently dropped, so the exclusion can be tested
    /// instead of taken on trust.
    pub(crate) fn speedrun_excluded_card_count(&mut self) -> Result<u32> {
        let search = format!("\"note:{ATTEMPT_NOTETYPE}\"");
        let guard = self.search_cards_into_table(search.as_str(), SortMode::NoOrder)?;
        let count = guard.col.storage.all_searched_cards()?.len();
        Ok(count as u32)
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn search_always_excludes_speedrun_attempt_cards() {
        let all = measurable_cards_search("", "mcat");
        assert!(all.contains(&format!("-\"note:{ATTEMPT_NOTETYPE}\"")));

        let section = measurable_cards_search("BB", "mcat");
        assert!(section.contains("\"tag:mcat::BB::*\""));
        assert!(section.contains(&format!("-\"note:{ATTEMPT_NOTETYPE}\"")));
    }

    #[test]
    fn empty_collection_reports_nothing_rather_than_zero_mastery() {
        let mut col = Collection::new();
        let res = col
            .speedrun_topic_mastery(TopicMasteryRequest {
                section: String::new(),
                tag_prefix: String::new(),
            })
            .unwrap();
        assert!(res.topics.is_empty());
        assert_eq!(res.cards_considered, 0);
        assert_eq!(res.cards_excluded, 0);
    }
}
