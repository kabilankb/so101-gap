"""Router: continue sorting (``pick``) or leave the loop (``finished``)."""

from gap import NodeContext


def run(ctx: NodeContext, finished: bool) -> dict:
    return {"route": "finished" if finished else "pick"}
