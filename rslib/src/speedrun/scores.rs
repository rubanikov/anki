// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Three scores, computed separately and never blended.
//!
//! Memory answers "can you recall a fact you were taught." Performance answers
//! "can you answer a question you have never seen." Readiness answers "what
//! would you score today." They are different questions, and a single number
//! that averages them is a worse answer to all three.
//!
//! Every one of them starts unavailable. A score is emitted only once it has
//! been earned, and an abstention always names the specific thing that would
//! resolve it.

use anki_proto::speedrun::Confidence;
use anki_proto::speedrun::Score;
use anki_proto::speedrun::SectionScoresRequest;
use anki_proto::speedrun::SectionScoresResponse;
use anki_proto::speedrun::TopicMasteryRequest;

use crate::prelude::*;
use crate::search::SortMode;
use crate::speedrun::thresholds::*;

/// A score that refuses to be a number, and says what would change that.
fn abstain(reason: impl Into<String>) -> Score {
    Score {
        available: false,
        estimate: 0.0,
        range_low: 0.0,
        range_high: 0.0,
        abstain_reason: reason.into(),
        reasons: vec![],
        confidence: Confidence::None as i32,
    }
}

fn available(estimate: f32, low: f32, high: f32, confidence: Confidence, reasons: Vec<String>) -> Score {
    Score {
        available: true,
        estimate,
        range_low: low,
        range_high: high,
        abstain_reason: String::new(),
        reasons,
        confidence: confidence as i32,
    }
}

impl Collection {
    pub(crate) fn speedrun_section_scores(
        &mut self,
        req: SectionScoresRequest,
    ) -> Result<SectionScoresResponse> {
        let section = req.section.clone();
        let computed_at_ms = TimestampSecs::now().0 * 1000;

        // The reading section has no content knowledge to model, by the AAMC's
        // own definition. Running the knowledge machinery on it and reporting a
        // number would be inventing one.
        if section.eq_ignore_ascii_case(UNMODELED_SECTION) {
            let reason = format!(
                "We don't model {UNMODELED_SECTION} knowledge, because the AAMC states there \
                 isn't any to model: everything needed to answer is in the passage."
            );
            return Ok(SectionScoresResponse {
                section,
                memory: Some(abstain(reason.clone())),
                performance: Some(abstain(reason.clone())),
                readiness: Some(abstain(reason)),
                coverage_pct: 0.0,
                graded_reviews: 0,
                holdout_attempts: 0,
                computed_at_ms,
            });
        }

        let mastery = self.speedrun_topic_mastery(TopicMasteryRequest {
            section: section.clone(),
            tag_prefix: req.tag_prefix.clone(),
        })?;

        let graded_reviews: u32 = mastery.topics.iter().map(|t| t.review_count).sum();
        let distinct_cards: u32 = mastery.topics.iter().map(|t| t.card_count).sum();
        let covered_topics = mastery.topics.iter().filter(|t| t.covered).count() as u32;
        let coverage_pct = if req.outline_topic_count > 0 {
            (covered_topics as f32 / req.outline_topic_count as f32) * 100.0
        } else {
            0.0
        };

        let memory = self.memory_score(&mastery, graded_reviews, distinct_cards, &section);
        let holdout_attempts = self.speedrun_holdout_attempt_count()?;
        let performance = performance_score(holdout_attempts, &section);

        // Readiness needs both of the scores beneath it plus enough of the
        // outline to be worth projecting from. Missing any one of those, it
        // abstains and names which.
        let readiness = if !memory.available {
            abstain(format!(
                "No readiness for {section} until memory is available: {}",
                memory.abstain_reason
            ))
        } else if !performance.available {
            abstain(format!(
                "No readiness for {section} until performance is available: {}",
                performance.abstain_reason
            ))
        } else if req.outline_topic_count == 0 {
            abstain(format!(
                "No outline loaded for {section}, so we cannot say what fraction of the exam \
                 you've covered."
            ))
        } else if coverage_pct < MIN_COVERAGE_PCT {
            abstain(format!(
                "You've covered {coverage_pct:.0}% of {section} ({covered_topics} of {} topics). \
                 Need {MIN_COVERAGE_PCT:.0}%.",
                req.outline_topic_count
            ))
        } else {
            // Deliberately still unavailable: the mapping from question
            // performance to a scaled score is not validated against any
            // student outcome data, and we will not ship a projected score we
            // cannot back up. See speedrun/docs/SCORE_MODEL.md.
            abstain(format!(
                "Thresholds for {section} are met, but the mapping from question performance to \
                 a scaled score is not yet validated against held-out outcomes. We'd rather say \
                 so than print a number."
            ))
        };

        Ok(SectionScoresResponse {
            section,
            memory: Some(memory),
            performance: Some(performance),
            readiness: Some(readiness),
            coverage_pct,
            graded_reviews,
            holdout_attempts,
            computed_at_ms,
        })
    }

    fn memory_score(
        &self,
        mastery: &anki_proto::speedrun::TopicMasteryResponse,
        graded_reviews: u32,
        distinct_cards: u32,
        section: &str,
    ) -> Score {
        if graded_reviews < MIN_GRADED_REVIEWS {
            return abstain(format!(
                "Only {graded_reviews} graded reviews in {section}. Need {MIN_GRADED_REVIEWS}."
            ));
        }
        if distinct_cards < MIN_DISTINCT_CARDS {
            return abstain(format!(
                "Only {distinct_cards} cards with history in {section}. Need {MIN_DISTINCT_CARDS}."
            ));
        }

        // Weighted by how many cards each topic actually has memory state for,
        // so a topic with two cards cannot swing the section mean.
        let mut weight_total = 0.0f64;
        let mut weighted_sum = 0.0f64;
        let mut weighted_low = 0.0f64;
        let mut weighted_high = 0.0f64;
        for topic in &mastery.topics {
            let w = topic.cards_with_memory_state as f64;
            if w == 0.0 {
                continue;
            }
            weight_total += w;
            weighted_sum += w * topic.mean_retrievability as f64;
            weighted_low += w * topic.range_low as f64;
            weighted_high += w * topic.range_high as f64;
        }
        if weight_total == 0.0 {
            return abstain(format!(
                "No cards in {section} have FSRS memory state yet, so there is nothing to \
                 estimate recall from."
            ));
        }

        let estimate = (weighted_sum / weight_total) as f32;
        let low = (weighted_low / weight_total) as f32;
        let high = (weighted_high / weight_total) as f32;
        let confidence = if graded_reviews >= MIN_GRADED_REVIEWS * 5 {
            Confidence::High
        } else if graded_reviews >= MIN_GRADED_REVIEWS * 2 {
            Confidence::Medium
        } else {
            Confidence::Low
        };

        available(
            estimate,
            low,
            high,
            confidence,
            vec![
                format!("{graded_reviews} graded reviews across {distinct_cards} cards"),
                format!("{} topics with history", mastery.topics.len()),
            ],
        )
    }

    /// Held-out attempts recorded so far. Only attempts tagged as held out
    /// count — anything the coach explained, hinted at, or reused for teaching
    /// is activity, not evidence.
    pub(crate) fn speedrun_holdout_attempt_count(&mut self) -> Result<u32> {
        let search = format!("\"note:{ATTEMPT_NOTETYPE}\" \"tag:{HOLDOUT_TAG}\"");
        let guard = self.search_cards_into_table(search.as_str(), SortMode::NoOrder)?;
        let count = guard.col.storage.all_searched_cards()?.len();
        Ok(count as u32)
    }
}

fn performance_score(holdout_attempts: u32, section: &str) -> Score {
    if holdout_attempts < MIN_HOLDOUT_ATTEMPTS {
        return abstain(format!(
            "Only {holdout_attempts} unhinted questions answered in {section}. Need \
             {MIN_HOLDOUT_ATTEMPTS}, across at least {MIN_DISTINCT_TOPICS_ATTEMPTED} topics."
        ));
    }
    abstain(format!(
        "{holdout_attempts} held-out attempts recorded in {section}, but the performance model \
         is not fitted yet."
    ))
}

#[cfg(test)]
mod test {
    use super::*;

    fn request(section: &str) -> SectionScoresRequest {
        SectionScoresRequest {
            section: section.to_string(),
            tag_prefix: String::new(),
            outline_topic_count: 0,
        }
    }

    /// (memory, performance, readiness)
    fn scores_for(section: &str) -> (Score, Score, Score) {
        let mut col = Collection::new();
        let res = col.speedrun_section_scores(request(section)).unwrap();
        (
            res.memory.unwrap(),
            res.performance.unwrap(),
            res.readiness.unwrap(),
        )
    }

    #[test]
    fn every_score_abstains_on_an_empty_collection() {
        let (memory, performance, readiness) = scores_for("BB");

        for score in [&memory, &performance, &readiness] {
            assert!(!score.available, "a score was emitted without data");
            assert_eq!(score.estimate, 0.0);
            assert!(
                !score.abstain_reason.is_empty(),
                "abstained without saying what would fix it"
            );
        }
        // The reason names the actual shortfall, not a generic message.
        assert!(memory.abstain_reason.contains("graded reviews"));
        assert!(performance.abstain_reason.contains("unhinted questions"));
    }

    #[test]
    fn cars_always_abstains_and_says_why() {
        let mut col = Collection::new();
        let res = col.speedrun_section_scores(request("CARS")).unwrap();

        assert!(!res.memory.unwrap().available);
        assert!(!res.performance.unwrap().available);
        let readiness = res.readiness.unwrap();
        assert!(!readiness.available);
        assert!(readiness.abstain_reason.contains("AAMC"));
        assert_eq!(res.coverage_pct, 0.0);
    }

    #[test]
    fn readiness_names_the_score_it_is_waiting_on() {
        let (_, _, readiness) = scores_for("CP");
        // Memory is the first thing missing, so readiness should point at it
        // rather than at coverage.
        assert!(readiness.abstain_reason.contains("memory is available"));
    }
}
