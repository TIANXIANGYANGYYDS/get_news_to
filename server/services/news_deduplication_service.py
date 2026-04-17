from domain.models.news_models import NewsEvent


class NewsDeduplicationService:
    def deduplicate(self, events: list[NewsEvent]) -> list[NewsEvent]:
        seen: set[str] = set()
        output: list[NewsEvent] = []
        for event in events:
            if event.event_id in seen:
                continue
            seen.add(event.event_id)
            output.append(event)
        return output
