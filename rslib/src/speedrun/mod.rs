// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Speedrun: measurement layered on top of Anki, never into it.
//!
//! Anki's review log is a years-long record of what one person actually learned
//! and how well it stuck. This module reads it. It never writes to it, never
//! adds an undo entry, and never touches a note, a card, or a review.
//!
//! Speedrun's own records live in a separate notetype whose cards are
//! suspended, and every query here filters them out — otherwise our own data
//! would inflate the numbers we grade ourselves on.

pub mod crosswalk;
mod mastery;
mod scores;
mod service;
pub mod thresholds;

/// A card's topic, derived from its tags.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Topic<'a> {
    /// The full tag, e.g. "mcat::BB::amino_acids".
    pub id: &'a str,
    /// The section component, e.g. "BB".
    pub section: &'a str,
}

/// Parse a topic out of a single tag, given the namespace root.
///
/// `mcat::BB::amino_acids` with prefix `mcat` yields section `BB`. A tag that
/// is only `mcat::BB` names a section but no topic within it, and is rejected —
/// we would have nothing to attribute mastery to.
pub(crate) fn topic_from_tag<'a>(tag: &'a str, prefix: &str) -> Option<Topic<'a>> {
    let rest = tag.strip_prefix(prefix)?.strip_prefix("::")?;
    let (section, remainder) = rest.split_once("::")?;
    if section.is_empty() || remainder.is_empty() {
        return None;
    }
    Some(Topic { id: tag, section })
}

/// The first tag on a note that names a topic, if any.
///
/// A note carrying several topic tags is attributed to one of them rather than
/// counted repeatedly. Double-counting a card across topics would quietly
/// inflate coverage, which is exactly the kind of number this project exists to
/// distrust.
pub(crate) fn topic_from_tags<'a>(tags: &'a [String], prefix: &str) -> Option<Topic<'a>> {
    tags.iter().find_map(|tag| topic_from_tag(tag, prefix))
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn topic_parsing_requires_a_topic_below_the_section() {
        let t = topic_from_tag("mcat::BB::amino_acids", "mcat").unwrap();
        assert_eq!(t.id, "mcat::BB::amino_acids");
        assert_eq!(t.section, "BB");

        // Section only — nothing to attribute mastery to.
        assert!(topic_from_tag("mcat::BB", "mcat").is_none());
        // Wrong namespace.
        assert!(topic_from_tag("anatomy::BB::x", "mcat").is_none());
        // Not a namespaced tag at all.
        assert!(topic_from_tag("leech", "mcat").is_none());
    }

    #[test]
    fn a_note_with_several_topic_tags_is_counted_once() {
        let tags = vec![
            "leech".to_string(),
            "mcat::CP::thermodynamics".to_string(),
            "mcat::CP::kinetics".to_string(),
        ];
        let t = topic_from_tags(&tags, "mcat").unwrap();
        assert_eq!(t.id, "mcat::CP::thermodynamics");
    }
}
