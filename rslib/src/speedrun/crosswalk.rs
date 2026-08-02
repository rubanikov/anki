// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! The Crosswalk: the student's own labels read as Outline topics.
//!
//! No real MCAT deck uses our section codes, so making a real collection
//! measurable would otherwise mean writing `mcat::` tags onto the student's
//! notes — a mutation that syncs to their phone and breaks the Sensor rule the
//! whole project rests on. Instead the mapping lives beside the collection, in
//! collection config, and is applied at read time. Nothing here writes a note,
//! a card, or a review.
//!
//! Two rules decide everything:
//!
//! - **Tags first, deck path only as a tiebreak.** Measuring the real deck
//!   (ADR-0005) found 182 hierarchical tags against 7 subject subdecks, and 26
//!   tags straddling several subdecks — `Biology::Genetics` files under
//!   *Biology*, *Biochemistry* and *Behavioral*. In every one of those cases the
//!   tag described the content and the subdeck was the accident of where the
//!   author filed it. A compound key would let the accident outvote the signal,
//!   so `decks` narrows an entry and never selects one.
//! - **A label that cannot be placed is refused, not guessed.** An entry may
//!   carry no topic at all. Its cards are then Unmapped cards, counted and
//!   reported. Filling one in to make coverage look better is the exact failure
//!   this project exists to refuse.

use serde::Deserialize;
use serde::Serialize;

use crate::prelude::*;

/// Collection config key holding the crosswalk.
///
/// Config rather than a new table: a schema change risks a forced one-way sync,
/// and a single blob written by one device is the only shape of state that
/// survives two devices editing offline.
pub const CROSSWALK_CONFIG_KEY: &str = "speedrunCrosswalk";

/// The crosswalk shipped with Speedrun, embedded so that desktop and Android
/// resolve topics from the same bytes with no network and no shared filesystem.
///
/// Bio/Biochem only — the demo section. Every other label a deck carries falls
/// through to Unmapped, which is a stated gap rather than a silent one.
pub const SHIPPED_CROSSWALK_JSON: &str =
    include_str!("../../../speedrun/crosswalk/miledown-bb-v1.json");

/// The mapping from a deck's own labels to Outline topics.
///
/// Consulted in the order written: the first entry that matches a card decides
/// it, and no later entry can overturn that. Order is the whole disambiguation
/// mechanism, which is why it is data rather than code.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Crosswalk {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub entries: Vec<CrosswalkEntry>,
}

/// One rule: this label means this topic.
///
/// `topic: None` is a deliberate refusal — the label was examined and found not
/// to separate two content categories — and it stops resolution just as a
/// mapping does, so a later, looser entry cannot quietly claim the cards.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CrosswalkEntry {
    /// A tag on the student's notes. Matches that tag and anything beneath it.
    pub tag: String,
    /// Optional deck paths this entry is restricted to. Empty means any deck.
    #[serde(default)]
    pub decks: Vec<String>,
    /// "BB" | "CP" | "PS".
    #[serde(default)]
    pub section: String,
    /// The AAMC content category, e.g. "1A". None means refused.
    #[serde(default)]
    pub topic: Option<String>,
    /// Why this entry says what it says. Carried so a mapping can be argued
    /// with rather than taken on trust.
    #[serde(default)]
    pub reason: String,
}

/// True if `tag` is `namespace` or sits beneath it.
///
/// Hierarchical, because a deck's tags are: an entry for
/// `Biochemistry::DNA_and_RNA` has to cover its eight children without listing
/// them, or the data file becomes a place mistakes hide.
fn tag_in_namespace(namespace: &str, tag: &str) -> bool {
    if namespace.is_empty() {
        return false;
    }
    let Some(head) = tag.get(..namespace.len()) else {
        return false;
    };
    if !head.eq_ignore_ascii_case(namespace) {
        return false;
    }
    let rest = &tag[namespace.len()..];
    rest.is_empty() || rest.starts_with("::")
}

impl CrosswalkEntry {
    fn matches(&self, tags: &[String], deck_path: &str) -> bool {
        // The deck is a filter on an already-chosen entry, never a selector.
        // Deck paths nest with `::` exactly as tags do, so a named deck covers
        // its subdecks.
        if !self.decks.is_empty()
            && !self
                .decks
                .iter()
                .any(|deck| tag_in_namespace(deck, deck_path))
        {
            return false;
        }
        tags.iter().any(|tag| tag_in_namespace(&self.tag, tag))
    }

    /// The topic id this entry attributes a card to, under the given namespace
    /// root. `None` for a refusal, and for an entry too malformed to name a
    /// topic — in both cases the card ends up counted as unmapped rather than
    /// attributed to something invented.
    pub(crate) fn topic_id(&self, prefix: &str) -> Option<(String, String)> {
        let topic = self.topic.as_deref()?;
        if topic.is_empty() || self.section.is_empty() {
            return None;
        }
        Some((
            format!("{prefix}::{}::{}", self.section, topic),
            self.section.clone(),
        ))
    }
}

impl Crosswalk {
    /// The first entry that claims this card, if any.
    ///
    /// Iteration is over entries rather than over the note's tags, so the
    /// answer depends only on the order of the data file and not on the order
    /// Anki happened to store the tags in.
    pub(crate) fn resolve(&self, tags: &[String], deck_path: &str) -> Option<&CrosswalkEntry> {
        self.entries
            .iter()
            .find(|entry| entry.matches(tags, deck_path))
    }
}

impl Collection {
    /// The crosswalk currently installed, if any.
    ///
    /// A missing or unparsable crosswalk yields `None`, which means every card
    /// without a native topic tag is reported as an Unmapped card. That is the
    /// loud failure: the count on screen goes to the size of the deck rather
    /// than mastery quietly being computed over a handful of cards.
    pub(crate) fn speedrun_crosswalk(&self) -> Option<Crosswalk> {
        self.get_config_optional(CROSSWALK_CONFIG_KEY)
    }

    /// Install a crosswalk.
    ///
    /// This writes collection *config* — Speedrun's own record, namespaced and
    /// excluded from every measurement. It does not touch a note, a card or a
    /// review, which is the line the Sensor rule actually draws.
    pub fn set_speedrun_crosswalk(&mut self, crosswalk: &Crosswalk) -> Result<()> {
        self.transact_no_undo(|col| {
            col.set_config(CROSSWALK_CONFIG_KEY, crosswalk)?;
            Ok(())
        })
    }
}

#[cfg(test)]
pub(crate) mod test {
    use super::*;

    pub(crate) fn entry(tag: &str, topic: Option<&str>) -> CrosswalkEntry {
        CrosswalkEntry {
            tag: tag.to_string(),
            decks: vec![],
            section: "BB".to_string(),
            topic: topic.map(ToString::to_string),
            reason: String::new(),
        }
    }

    fn tags(list: &[&str]) -> Vec<String> {
        list.iter().map(ToString::to_string).collect()
    }

    #[test]
    fn a_tag_entry_covers_the_tags_beneath_it() {
        let cw = Crosswalk {
            id: "t".into(),
            entries: vec![entry("MileDown::Biochemistry::DNA_and_RNA", Some("1B"))],
        };
        for tag in [
            "MileDown::Biochemistry::DNA_and_RNA",
            "MileDown::Biochemistry::DNA_and_RNA::Translation",
            "milEdown::biochemistry::dna_and_rna::repair",
        ] {
            assert!(
                cw.resolve(&tags(&[tag]), "Any").is_some(),
                "{tag} should have resolved"
            );
        }
        // A sibling that merely shares a prefix is not beneath it.
        assert!(cw
            .resolve(&tags(&["MileDown::Biochemistry::DNA_and_RNA_Extra"]), "Any")
            .is_none());
    }

    #[test]
    fn entry_order_decides_and_not_tag_order() {
        let cw = Crosswalk {
            id: "t".into(),
            entries: vec![
                entry("A::Second", Some("1B")),
                entry("A::First", Some("1A")),
            ],
        };
        // Same two tags, opposite orders on the note: the file decides.
        let forwards = cw.resolve(&tags(&["A::First", "A::Second"]), "d").unwrap();
        let backwards = cw.resolve(&tags(&["A::Second", "A::First"]), "d").unwrap();
        assert_eq!(forwards.topic_id("mcat"), backwards.topic_id("mcat"));
        assert_eq!(
            forwards.topic_id("mcat").unwrap().0,
            "mcat::BB::1B".to_string()
        );
    }

    #[test]
    fn an_ambiguous_label_is_refused_rather_than_assigned() {
        let cw = Crosswalk {
            id: "t".into(),
            entries: vec![
                entry("MileDown::Biology::Reproduction::Meiosis", Some("1C")),
                // Refusal: the bare tag splits across four categories.
                entry("MileDown::Biology::Reproduction", None),
                // A later, looser entry must not be able to claim them.
                entry("MileDown::Biology", Some("3B")),
            ],
        };

        let child = cw
            .resolve(&tags(&["MileDown::Biology::Reproduction::Meiosis"]), "d")
            .unwrap();
        assert_eq!(child.topic_id("mcat").unwrap().0, "mcat::BB::1C");

        let refused = cw
            .resolve(&tags(&["MileDown::Biology::Reproduction"]), "d")
            .unwrap();
        assert!(
            refused.topic_id("mcat").is_none(),
            "a refused label was given a topic"
        );
    }

    #[test]
    fn the_deck_path_narrows_an_entry_and_never_selects_one() {
        let mut restricted = entry("MileDown::Biology::Immune_System", Some("3B"));
        restricted.decks = vec!["MileDown's MCAT Decks::Biology".to_string()];
        let cw = Crosswalk {
            id: "t".into(),
            entries: vec![
                restricted,
                entry("MileDown::Biochemistry::Lipid_Metabolism", Some("1D")),
            ],
        };

        let tags_of_misfiled_card = tags(&[
            "MileDown::Biochemistry::Lipid_Metabolism",
            "MileDown::Biology::Immune_System",
        ]);

        // In the Biology subdeck the immune entry applies.
        assert_eq!(
            cw.resolve(&tags_of_misfiled_card, "MileDown's MCAT Decks::Biology")
                .unwrap()
                .topic_id("mcat")
                .unwrap()
                .0,
            "mcat::BB::3B"
        );
        // Filed under Biochemistry, the same tag does not, and the card falls
        // through to the entry that describes what it is actually about.
        assert_eq!(
            cw.resolve(
                &tags_of_misfiled_card,
                "MileDown's MCAT Decks::Biochemistry"
            )
            .unwrap()
            .topic_id("mcat")
            .unwrap()
            .0,
            "mcat::BB::1D"
        );
        // A deck path alone, with no matching tag, resolves nothing.
        assert!(cw
            .resolve(&tags(&["unrelated"]), "MileDown's MCAT Decks::Biology")
            .is_none());
    }

    #[test]
    fn a_deck_restriction_covers_subdecks_of_the_named_deck() {
        let mut restricted = entry("Some::Tag", Some("2A"));
        restricted.decks = vec!["Parent".to_string()];
        let cw = Crosswalk {
            id: "t".into(),
            entries: vec![restricted],
        };
        assert!(cw.resolve(&tags(&["Some::Tag"]), "Parent").is_some());
        assert!(cw.resolve(&tags(&["Some::Tag"]), "Parent::Child").is_some());
        assert!(cw.resolve(&tags(&["Some::Tag"]), "ParentOther").is_none());
    }

    #[test]
    fn the_shipped_bio_biochem_file_parses_and_refuses_what_it_says_it_refuses() {
        // The data file is the deliverable; a typo in it is a silent
        // measurement error, so it is parsed in CI rather than by hand.
        let cw: Crosswalk =
            serde_json::from_str(SHIPPED_CROSSWALK_JSON).expect("crosswalk file should parse");
        assert_eq!(cw.id, "miledown-bb-v1");

        let mapped: Vec<_> = cw
            .entries
            .iter()
            .filter_map(|e| e.topic_id("mcat").map(|(id, _)| id))
            .collect();
        // Every Bio/Biochem content category is reachable. 9 of 9, per the
        // deck report; a crosswalk that quietly stopped covering one would
        // report that topic as uncovered forever.
        for category in ["1A", "1B", "1C", "1D", "2A", "2B", "2C", "3A", "3B"] {
            assert!(
                mapped
                    .iter()
                    .any(|id| id == &format!("mcat::BB::{category}")),
                "no entry maps to {category}"
            );
        }
        // And nothing outside the demo section sneaks in.
        assert!(mapped.iter().all(|id| id.starts_with("mcat::BB::")));

        // The refusals are load-bearing: each one names why.
        let refusals: Vec<_> = cw.entries.iter().filter(|e| e.topic.is_none()).collect();
        assert!(refusals.len() >= 4);
        assert!(refusals.iter().all(|e| !e.reason.is_empty()));
        assert!(refusals
            .iter()
            .any(|e| e.tag == "MileDown::Biochemistry::Lab_Techniques"));
    }
}
