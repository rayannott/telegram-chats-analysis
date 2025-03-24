from typing import Optional
from datetime import datetime
from dataclasses import dataclass, field

# @dataclass
# class Reaction:
#     emoji: str
#     count: int


@dataclass
class Message:
    id: int
    from_: str
    text: str
    dt: datetime
    edited_dt: datetime | None = None
    reply_to_id: int | None = None
    reply_to: Optional["Message"] = None
    other_text_entity_types: set[str] = field(default_factory=set)
    # reactions: list[Reaction] = field(default_factory=list)

    @classmethod
    def from_dict(cls, json_data: dict) -> "Message":
        return cls(
            id=json_data["id"],
            from_=json_data["from"],
            text=txt
            if (txt := json_data["text"])
            else "".join(te["text"] for te in json_data.get("text_entities", [])),
            dt=datetime.fromisoformat(json_data["date"]),
            edited_dt=datetime.fromisoformat(json_data["edited"])
            if json_data.get("edited")
            else None,
            reply_to_id=json_data.get("reply_to_message_id"),
            other_text_entity_types={
                tp
                for te in json_data.get("text_entities", [])
                if (tp := te["type"]) != "plain"
            },
        )

    def __str__(self) -> str:
        return f"[{self.from_}] {self.text} ({self.dt:%d.%m.%Y %H:%M})"


def reply_chain(message: Message) -> list[Message]:
    res = [message]
    if message.reply_to is None:
        return res
    return res + reply_chain(message.reply_to)
