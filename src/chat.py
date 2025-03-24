import json
import datetime
from typing import Literal, Callable
from pathlib import Path
from collections import defaultdict

import plotly.graph_objects as go

from src.message import Message


GroupbyKeys = Literal["day", "week", "month"]


class Chat:
    def __init__(self, exported_file: Path):
        with exported_file.open(encoding="utf-8") as f:
            self.data = json.load(f)
        self.chat_with = self.data["name"]
        if self.data["type"] != "personal_chat":
            raise NotImplementedError("Only personal chats are supported")
        messages_map = {
            (this_msg := Message.from_dict(msg)).id: this_msg
            for msg in self.data["messages"]
            if msg["type"] == "message"
        }
        for msg in messages_map.values():
            if msg.reply_to_id is not None:
                replied_to = messages_map[msg.reply_to_id]
                msg.reply_to = replied_to
        self.messages = list(messages_map.values())

    def __repr__(self) -> str:
        return f"Chat({self.chat_with}; {len(self.messages)} messages)"

    def groupby(
        self, key: GroupbyKeys
    ) -> defaultdict[datetime.date | datetime.datetime, list[Message]]:
        """Group messages by day, week, or month."""
        KEYMAP: dict[
            GroupbyKeys,
            Callable[[Message], datetime.date | datetime.datetime],
        ] = {
            "day": lambda x: x.dt.date(),
            "week": lambda x: (x.dt - datetime.timedelta(days=x.dt.weekday())).date(),
            "month": lambda x: x.dt.date().replace(day=1),
        }
        grouped = defaultdict(list)
        for msg in self.messages:
            grouped[KEYMAP[key](msg)].append(msg)
        return grouped

    def get_trace_messages_by(self, groupby_key: GroupbyKeys) -> go.Scatter:
        """Get a line chart trace with the number of messages by day/week/month."""
        group = self.groupby(groupby_key)
        days = list(group.keys())
        n_messages_lst = [len(day_msgs) for day_msgs in group.values()]
        return go.Scatter(
            x=days,
            y=n_messages_lst,
            mode="lines+markers",
            line_shape="spline",
            name=self.chat_with,
        )


class Chats:
    def __init__(self, chats: list[Chat]):
        self.chats = chats
        ...

    def fig_bar(self, messages_include: str | None = None) -> go.Figure:
        """Plot a bar chart with the number of messages in each chat.
        Optionally, include only messages that contain a specific string."""
        chat_names = []
        message_counts = []
        for chat in self.chats:
            n_messages = sum(
                1
                for msg in chat.messages
                if messages_include is None or messages_include in msg.text
            )
            chat_names.append(chat.chat_with)
            message_counts.append(n_messages)
        fig = go.Figure(
            go.Bar(
                x=chat_names,
                y=message_counts,
            )
        )
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            template="plotly_dark",
            yaxis_title="Number of messages",
        )
        return fig

    def fig_messages_by(self, groupby_key: GroupbyKeys):
        """Plot a line chart with the number of messages by day."""
        fig = go.Figure()
        for chat in self.chats:
            trace = chat.get_trace_messages_by(groupby_key)
            fig.add_trace(trace)
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            template="plotly_dark",
        )
        fig.update_xaxes(title_text=groupby_key.capitalize())
        fig.update_yaxes(title_text="Number of messages")
        return fig
