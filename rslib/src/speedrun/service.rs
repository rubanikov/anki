// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

use crate::collection::Collection;
use crate::error;

impl crate::services::SpeedrunService for Collection {
    fn topic_mastery(
        &mut self,
        input: anki_proto::speedrun::TopicMasteryRequest,
    ) -> error::Result<anki_proto::speedrun::TopicMasteryResponse> {
        self.speedrun_topic_mastery(input)
    }

    fn section_scores(
        &mut self,
        input: anki_proto::speedrun::SectionScoresRequest,
    ) -> error::Result<anki_proto::speedrun::SectionScoresResponse> {
        self.speedrun_section_scores(input)
    }
}
