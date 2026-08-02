// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! The give-up rule.
//!
//! These live in the backend rather than the UI on purpose. Abstention is the
//! default state of every score, and both the desktop add-on and the Android
//! client inherit it by construction — neither can talk its way past a
//! threshold, because neither is asked.

/// Notetype holding Speedrun's own attempt records. Its cards are suspended and
/// excluded from every measurement; see [`crate::speedrun::mastery`].
pub const ATTEMPT_NOTETYPE: &str = "Speedrun::Attempt";

/// Tag marking an attempt as belonging to the held-out set. Only these count
/// toward the performance score.
pub const HOLDOUT_TAG: &str = "speedrun::holdout";

/// Default root of the topic tag namespace.
pub const DEFAULT_TAG_PREFIX: &str = "mcat";

/// The reading section has no content knowledge to model, by the AAMC's own
/// definition, so the knowledge machinery never runs on it.
pub const UNMODELED_SECTION: &str = "CARS";

pub const MIN_GRADED_REVIEWS: u32 = 200;
pub const MIN_DISTINCT_CARDS: u32 = 30;

/// Below twenty attempts the 95% interval around a 60% success rate is already
/// ±21 points — wider than the quantity being measured. This is the floor at
/// which a performance number still says something, not a convenient one.
pub const MIN_HOLDOUT_ATTEMPTS: u32 = 20;

pub const MIN_COVERAGE_PCT: f32 = 50.0;

/// Content categories on the AAMC outline, per section.
///
/// A topic is one lettered content category (1A, 5C, ...). CARS has none: it is
/// skills-based by the AAMC's own description, which is why we never model it.
pub fn outline_topic_count(section: &str) -> u32 {
    match section.to_ascii_uppercase().as_str() {
        "BB" => 9,
        "CP" => 10,
        "PS" => 12,
        _ => 0,
    }
}

/// How many distinct topics must have been attempted before performance reports.
///
/// A fraction of the section rather than a flat count. The previous absolute 8
/// demanded 89% of Bio/Biochem but only 67% of Psych/Soc, so the same rule meant
/// something different in every section and performance would have abstained
/// essentially forever.
pub fn min_distinct_topics_attempted(section: &str) -> u32 {
    let total = outline_topic_count(section);
    if total == 0 {
        return 0;
    }
    total.div_ceil(3)
}

/// The AAMC reports a standard error of roughly ±2 points on the scaled score,
/// across 305,494 exams. We are measuring through their instrument, so we
/// cannot be more precise than it is. Any interval we compute that comes out
/// tighter than this is widened.
pub const AAMC_SEM_POINTS: f32 = 2.0;

/// Widen a scaled-score interval to at least the AAMC's own standard error.
///
/// Returns `(low, high)`. A tighter interval is not a better one — it is a
/// claim the underlying instrument cannot support.
pub fn widen_to_aamc_sem(estimate: f32, low: f32, high: f32) -> (f32, f32) {
    let floor_low = estimate - AAMC_SEM_POINTS;
    let floor_high = estimate + AAMC_SEM_POINTS;
    (low.min(floor_low), high.max(floor_high))
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn the_topic_requirement_scales_with_the_section() {
        // Bio/Biochem has 9 content categories, Chem/Phys 10, Psych/Soc 12.
        assert_eq!(min_distinct_topics_attempted("BB"), 3);
        assert_eq!(min_distinct_topics_attempted("CP"), 4);
        assert_eq!(min_distinct_topics_attempted("PS"), 4);
        // A section we do not model cannot have a topic requirement.
        assert_eq!(min_distinct_topics_attempted("CARS"), 0);
        assert_eq!(min_distinct_topics_attempted(""), 0);
    }

    #[test]
    fn tight_intervals_are_widened_to_the_aamc_sem() {
        // A model that thinks it knows the score to within half a point does
        // not get to say so.
        let (low, high) = widen_to_aamc_sem(508.0, 507.5, 508.5);
        assert_eq!(low, 506.0);
        assert_eq!(high, 510.0);
    }

    #[test]
    fn intervals_wider_than_the_sem_are_left_alone() {
        let (low, high) = widen_to_aamc_sem(508.0, 501.0, 515.0);
        assert_eq!(low, 501.0);
        assert_eq!(high, 515.0);
    }

    #[test]
    fn widening_is_one_sided_per_bound() {
        // Tight on the low side, already wide on the high side.
        let (low, high) = widen_to_aamc_sem(508.0, 507.9, 514.0);
        assert_eq!(low, 506.0);
        assert_eq!(high, 514.0);
    }
}
