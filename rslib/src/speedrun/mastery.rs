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
use crate::speedrun::crosswalk::Crosswalk;
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
///
/// With a Crosswalk installed the tag clause has to go. A real deck carries
/// none of our tags — that is the entire reason the crosswalk exists — so
/// scoping the search to `mcat::*` would return nothing and report a deck of
/// three thousand cards as empty. Instead every card the student owns is read
/// and the topic is resolved per card, which is also what lets the unmapped
/// count be a real number rather than an inference.
fn measurable_cards_search(section: &str, tag_prefix: &str, crosswalk_installed: bool) -> String {
    let exclusion = format!("-\"note:{ATTEMPT_NOTETYPE}\"");
    if crosswalk_installed {
        return exclusion;
    }
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
    format!("\"tag:{tag}\" {exclusion}")
}

/// What a single card was attributed to.
struct Attribution {
    topic_id: String,
    section: String,
}

/// Resolve one card's topic: its own tags first, then the crosswalk.
///
/// A note that already carries a topic tag is taken at its word — that is the
/// collection speaking for itself, and the crosswalk is only ever a
/// substitute for a label the deck does not have. Neither path writes anything
/// back; a resolution that ended in a tag being added to a note would be the
/// Sensor rule broken.
fn attribute(
    tags: &[String],
    deck_path: &str,
    prefix: &str,
    crosswalk: Option<&Crosswalk>,
) -> Option<Attribution> {
    if let Some(topic) = topic_from_tags(tags, prefix) {
        return Some(Attribution {
            topic_id: topic.id.to_string(),
            section: topic.section.to_string(),
        });
    }
    let entry = crosswalk?.resolve(tags, deck_path)?;
    let (topic_id, section) = entry.topic_id(prefix)?;
    Some(Attribution { topic_id, section })
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
        let crosswalk = self.speedrun_crosswalk();
        let search = measurable_cards_search(&req.section, &prefix, crosswalk.is_some());

        // Borrowed before the search guards, which hold &mut self.
        let timing = self.timing_today()?;
        // Deck path is a tiebreak inside the crosswalk, so it is only needed
        // when one is installed.
        let deck_names: HashMap<DeckId, String> = if crosswalk.is_some() {
            self.storage.get_all_deck_names()?.into_iter().collect()
        } else {
            HashMap::new()
        };

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
        let mut cards_unresolved = 0u32;

        for card in &cards {
            let Some(tags) = tags_by_note.get(&card.note_id) else {
                continue;
            };
            // The home deck, so a card sitting in a filtered deck is still read
            // as belonging where the student filed it.
            let deck_id = if card.original_deck_id.0 == 0 {
                card.deck_id
            } else {
                card.original_deck_id
            };
            let deck_path = deck_names.get(&deck_id).map(String::as_str).unwrap_or("");

            let Some(topic) = attribute(tags, deck_path, &prefix, crosswalk.as_ref()) else {
                cards_unresolved += 1;
                continue;
            };
            // Resolved, but to a different section than the caller asked about.
            // Not measured here and not unmapped either.
            if !req.section.is_empty() && !topic.section.eq_ignore_ascii_case(&req.section) {
                continue;
            }
            cards_considered += 1;

            let entry = topics.entry(topic.topic_id.clone()).or_default();
            if entry.section.is_empty() {
                entry.section = topic.section.clone();
            }
            entry.cards += 1;
            entry.reviews += card.reps;

            // A card FSRS has no memory state for cannot contribute a
            // probability. We count it toward coverage and leave it out of the
            // mean rather than inventing a value for it.
            if let Some(state) = card.memory_state {
                let elapsed_days =
                    card.seconds_since_last_review(&timing).unwrap_or_default() as f32 / 86_400.0;
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

        // With a crosswalk the pass above already saw every card in the
        // collection, so the misses are counted rather than searched for —
        // and they are crosswalk misses, not merely cards without our tags.
        let cards_unmapped = if crosswalk.is_some() {
            cards_unresolved
        } else {
            self.speedrun_unmapped_card_count(&prefix)?
        };

        Ok(TopicMasteryResponse {
            topics: out,
            cards_considered,
            cards_excluded,
            cards_unmapped,
        })
    }

    /// Cards the crosswalk could not place under any topic.
    ///
    /// The fallback used when no crosswalk is installed, where "unplaceable"
    /// can only mean "carries no topic tag". With one installed the count comes
    /// from the resolution pass instead, so that a card the crosswalk was
    /// offered and declined is counted too.
    ///
    /// Deliberately collection-wide rather than per-section: "how much of your
    /// deck can we not place?" is a question about the deck, and the answer
    /// must not shrink when the caller narrows to one section. Without this
    /// number the denominator is invisible — a deck where a third of the
    /// cards resolve would report confident mastery and never mention the
    /// other two thirds.
    pub(crate) fn speedrun_unmapped_card_count(&mut self, tag_prefix: &str) -> Result<u32> {
        let search = format!("-\"note:{ATTEMPT_NOTETYPE}\" -\"tag:{tag_prefix}::*\"");
        let guard = self.search_cards_into_table(search.as_str(), SortMode::NoOrder)?;
        let count = guard.col.storage.all_searched_cards()?.len();
        Ok(count as u32)
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
    use std::collections::hash_map::DefaultHasher;
    use std::hash::Hash;
    use std::hash::Hasher;

    use super::*;
    use crate::speedrun::crosswalk::test::entry;
    use crate::speedrun::crosswalk::Crosswalk;
    use crate::tests::open_fs_test_collection;
    use crate::tests::DeckAdder;

    const BIOLOGY: &str = "MileDown's MCAT Decks::Biology";
    const BIOCHEM: &str = "MileDown's MCAT Decks::Biochemistry";

    /// A crosswalk shaped like the shipped one: a mapping, a deck-restricted
    /// mapping, and a refusal.
    fn miledown_crosswalk() -> Crosswalk {
        let mut restricted = entry("MileDown::Biology::Immune_System", Some("3B"));
        restricted.decks = vec![BIOLOGY.to_string()];
        Crosswalk {
            id: "test".into(),
            entries: vec![
                entry("MileDown::Biochemistry::Amino_Acids", Some("1A")),
                entry("MileDown::Biochemistry::DNA_and_RNA", Some("1B")),
                restricted,
                entry("MileDown::Biochemistry::Lipid_Metabolism", Some("1D")),
                // Examined and refused: the label does not separate 9A from 9B.
                entry("MileDown::Behavioral::Social::Social_Structure", None),
            ],
        }
    }

    fn deck(col: &mut Collection, name: &str) -> DeckId {
        DeckAdder::new(name).add(col).id
    }

    fn add_tagged_note(col: &mut Collection, deck: DeckId, tags: &[&str]) {
        let notetype = col.basic_notetype();
        let mut note = notetype.new_note();
        note.tags = tags.iter().map(ToString::to_string).collect();
        col.add_note(&mut note, deck).unwrap();
    }

    fn mastery(col: &mut Collection, section: &str) -> TopicMasteryResponse {
        col.speedrun_topic_mastery(TopicMasteryRequest {
            section: section.to_string(),
            tag_prefix: String::new(),
        })
        .unwrap()
    }

    fn topic_ids(res: &TopicMasteryResponse) -> Vec<&str> {
        res.topics.iter().map(|t| t.topic_id.as_str()).collect()
    }

    #[test]
    fn search_always_excludes_speedrun_attempt_cards() {
        let all = measurable_cards_search("", "mcat", false);
        assert!(all.contains(&format!("-\"note:{ATTEMPT_NOTETYPE}\"")));

        let section = measurable_cards_search("BB", "mcat", false);
        assert!(section.contains("\"tag:mcat::BB::*\""));
        assert!(section.contains(&format!("-\"note:{ATTEMPT_NOTETYPE}\"")));

        // With a crosswalk the tag scope is dropped — a real deck has none of
        // our tags — but the exclusion is not, because it is the only thing
        // keeping our own attempt records out of the number.
        let crosswalked = measurable_cards_search("BB", "mcat", true);
        assert!(!crosswalked.contains("tag:mcat"));
        assert!(crosswalked.contains(&format!("-\"note:{ATTEMPT_NOTETYPE}\"")));
    }

    #[test]
    fn empty_collection_reports_nothing_rather_than_zero_mastery() {
        let mut col = Collection::new();
        let res = mastery(&mut col, "");
        assert!(res.topics.is_empty());
        assert_eq!(res.cards_considered, 0);
        assert_eq!(res.cards_excluded, 0);
        assert_eq!(res.cards_unmapped, 0);
    }

    #[test]
    fn cards_with_no_resolvable_topic_are_counted_not_dropped() {
        let search = measurable_cards_search("", "mcat", false);
        // Without a crosswalk the measured set is tag-scoped, so an untagged
        // card can never appear in it. That is precisely why the unmapped count
        // has to be asked for separately rather than inferred from what the
        // search returned.
        assert!(search.contains("\"tag:mcat::*\""));

        let mut col = Collection::new();
        assert_eq!(col.speedrun_unmapped_card_count("mcat").unwrap(), 0);
    }

    #[test]
    fn a_collection_with_no_mcat_tags_still_produces_per_topic_mastery() {
        let mut col = Collection::new();
        let biochem = deck(&mut col, BIOCHEM);
        add_tagged_note(&mut col, biochem, &["MileDown::Biochemistry::Amino_Acids"]);
        add_tagged_note(
            &mut col,
            biochem,
            &["MileDown::Biochemistry::DNA_and_RNA::Translation"],
        );

        // Nothing in this collection carries an mcat:: tag, and nothing here
        // adds one.
        let before = mastery(&mut col, "BB");
        assert!(before.topics.is_empty());
        assert_eq!(before.cards_unmapped, 2);

        col.set_speedrun_crosswalk(&miledown_crosswalk()).unwrap();

        let after = mastery(&mut col, "BB");
        assert_eq!(topic_ids(&after), vec!["mcat::BB::1A", "mcat::BB::1B"]);
        assert_eq!(after.cards_considered, 2);
        assert_eq!(after.cards_unmapped, 0);

        // The notes themselves are untouched: still their own tags, still no
        // tag of ours.
        for note in col.get_all_notes() {
            assert!(
                note.tags.iter().all(|tag| !tag.starts_with("mcat")),
                "resolution wrote a topic tag onto a note"
            );
        }
    }

    #[test]
    fn a_card_matching_no_crosswalk_entry_lands_in_unmapped() {
        let mut col = Collection::new();
        let biochem = deck(&mut col, BIOCHEM);
        add_tagged_note(&mut col, biochem, &["MileDown::Biochemistry::Amino_Acids"]);
        add_tagged_note(&mut col, biochem, &["MileDown::Physics::Research::Data"]);
        add_tagged_note(&mut col, biochem, &[]);
        col.set_speedrun_crosswalk(&miledown_crosswalk()).unwrap();

        let res = mastery(&mut col, "BB");
        assert_eq!(res.cards_considered, 1);
        // Research design and an untagged card: two cards the crosswalk cannot
        // place, reported rather than dropped so the denominator is stated.
        assert_eq!(res.cards_unmapped, 2);
    }

    #[test]
    fn an_ambiguous_label_is_left_unmapped_rather_than_assigned() {
        let mut col = Collection::new();
        let behavioral = deck(&mut col, "MileDown's MCAT Decks::Behavioral");
        add_tagged_note(
            &mut col,
            behavioral,
            &["MileDown::Behavioral::Social::Social_Structure"],
        );
        col.set_speedrun_crosswalk(&miledown_crosswalk()).unwrap();

        // 9A and 9B are fused in this one label. Guessing either would inflate
        // one category and report the other as never studied.
        let res = mastery(&mut col, "");
        assert!(
            res.topics.is_empty(),
            "an ambiguous label was assigned a topic: {:?}",
            topic_ids(&res)
        );
        assert_eq!(res.cards_considered, 0);
        assert_eq!(res.cards_unmapped, 1);
    }

    #[test]
    fn the_deck_path_only_breaks_ties_between_tags() {
        let mut col = Collection::new();
        let biology = deck(&mut col, BIOLOGY);
        let biochem = deck(&mut col, BIOCHEM);
        add_tagged_note(&mut col, biology, &["MileDown::Biology::Immune_System"]);
        // The same tag, filed in the wrong subdeck by the deck's author. Its
        // other tag describes what the card is actually about.
        add_tagged_note(
            &mut col,
            biochem,
            &[
                "MileDown::Biology::Immune_System",
                "MileDown::Biochemistry::Lipid_Metabolism",
            ],
        );
        col.set_speedrun_crosswalk(&miledown_crosswalk()).unwrap();

        let res = mastery(&mut col, "BB");
        assert_eq!(topic_ids(&res), vec!["mcat::BB::1D", "mcat::BB::3B"]);
        assert_eq!(res.cards_unmapped, 0);
    }

    #[test]
    fn speedruns_own_attempt_cards_stay_excluded_with_a_crosswalk_installed() {
        let mut col = Collection::new();
        let biochem = deck(&mut col, BIOCHEM);
        add_tagged_note(&mut col, biochem, &["MileDown::Biochemistry::Amino_Acids"]);

        // An attempt note carries a topic tag of its own, so with the tag scope
        // dropped it is only the notetype exclusion that keeps our own records
        // from inflating the number we grade ourselves on.
        let mut attempt_notetype = col.basic_notetype();
        attempt_notetype.id = NotetypeId(0);
        attempt_notetype.name = ATTEMPT_NOTETYPE.to_string();
        col.add_notetype(&mut attempt_notetype, false).unwrap();
        let mut attempt = attempt_notetype.new_note();
        attempt.tags = vec!["mcat::BB::1A".to_string()];
        col.add_note(&mut attempt, biochem).unwrap();

        col.set_speedrun_crosswalk(&miledown_crosswalk()).unwrap();

        let res = mastery(&mut col, "BB");
        assert_eq!(res.cards_excluded, 1);
        assert_eq!(res.cards_considered, 1, "an attempt card reached mastery");
        assert_eq!(res.topics[0].card_count, 1);
        // And an excluded card is not an unmapped one either.
        assert_eq!(res.cards_unmapped, 0);
    }

    #[test]
    fn the_shipped_crosswalk_measures_a_miledown_shaped_deck() {
        let mut col = Collection::new();
        let biochem = deck(&mut col, BIOCHEM);
        let biology = deck(&mut col, BIOLOGY);
        add_tagged_note(&mut col, biochem, &["MileDown::Biochemistry::Amino_Acids"]);
        add_tagged_note(
            &mut col,
            biology,
            &["MileDown::Biology::Nervous_System::Synapses"],
        );
        // Refused by the shipped file: 1B biotechnology and 5C protein
        // separation share this one label.
        add_tagged_note(
            &mut col,
            biochem,
            &["MileDown::Biochemistry::Lab_Techniques"],
        );

        let shipped: Crosswalk =
            serde_json::from_str(crate::speedrun::crosswalk::SHIPPED_CROSSWALK_JSON).unwrap();
        col.set_speedrun_crosswalk(&shipped).unwrap();

        let res = mastery(&mut col, "BB");
        assert_eq!(topic_ids(&res), vec!["mcat::BB::1A", "mcat::BB::3A"]);
        assert_eq!(res.cards_considered, 2);
        assert_eq!(res.cards_unmapped, 1);
    }

    fn hash_of(bytes: &[u8]) -> u64 {
        let mut hasher = DefaultHasher::new();
        bytes.hash(&mut hasher);
        hasher.finish()
    }

    /// Every note, card and review, in a stable order.
    ///
    /// The thing the Sensor rule is actually about. Hashing the file alone
    /// would let a change to the student's notes hide behind a change to
    /// Anki's own bookkeeping, and vice versa.
    fn student_data_fingerprint(col: &Collection) -> String {
        col.storage
            .db
            .query_row(
                "select coalesce(group_concat(x, char(10)), '') from (
                   select 'n'||id||' '||mod||' '||usn||' '||tags||' '||flds as x from notes
                   union all
                   select 'c'||id||' '||nid||' '||did||' '||odid||' '||mod||' '||usn||' '
                          ||reps||' '||lapses||' '||ivl||' '||due||' '||queue||' '||type from cards
                   union all
                   select 'r'||id||' '||cid||' '||ease||' '||ivl||' '||time||' '||type from revlog
                   order by x)",
                [],
                |row| row.get(0),
            )
            .unwrap()
    }

    #[test]
    fn measuring_never_writes_to_the_collection() {
        let (mut col, _tempdir) = open_fs_test_collection("speedrun_sensor");
        let biology = deck(&mut col, BIOLOGY);
        add_tagged_note(&mut col, biology, &["MileDown::Biology::Immune_System"]);
        add_tagged_note(&mut col, biology, &["MileDown::Physics::Research"]);
        col.set_speedrun_crosswalk(&miledown_crosswalk()).unwrap();

        let student_data_before = student_data_fingerprint(&col);

        // The first call to any Anki API that asks what day it is may rewrite
        // the stored timezone offset in config — stock Anki bookkeeping, not
        // ours, and not the student's data. Stating it rather than hiding it:
        // the file hash is taken after that has settled, and the fingerprint
        // below is taken from before the very first call, so a write to a note,
        // a card or a review would still be caught.
        let _ = mastery(&mut col, "BB");
        col.storage.checkpoint().unwrap();
        let path = col.col_path.clone();
        let before = hash_of(&std::fs::read(&path).unwrap());

        for _ in 0..200 {
            let res = mastery(&mut col, "BB");
            assert_eq!(res.cards_considered, 1);
            assert_eq!(res.cards_unmapped, 1);
        }

        col.storage.checkpoint().unwrap();
        let after = hash_of(&std::fs::read(&path).unwrap());
        assert_eq!(
            before, after,
            "the collection file changed while being measured"
        );
        assert_eq!(
            student_data_before,
            student_data_fingerprint(&col),
            "a note, card or review changed while being measured; the sensor rule is broken"
        );
    }
}
