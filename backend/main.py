from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import os

app = FastAPI(title="Agenda de Visitas API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..")


# ── Models ──────────────────────────────────────────────────

class Visit(BaseModel):
    id: str
    client: str
    property: str
    start: str
    end: str
    manualAgent: Optional[str] = None
    example: bool = False


class Agent(BaseModel):
    id: str
    name: str
    startTime: Optional[str] = ""
    endTime: Optional[str] = ""
    example: bool = False


class ScheduleRequest(BaseModel):
    visits: list[Visit]
    agents: list[Agent]
    travelTime: int = 20


# ── Helpers ─────────────────────────────────────────────────

def to_min(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


# ── Algorithms ──────────────────────────────────────────────

def interval_partitioning(visits: list[Visit], travel_time: int) -> tuple[int, dict]:
    """
    Minimum number of agents to cover all visits without overlap.
    Greedy: sort by start time, reuse the agent that became free latest
    (but still free with travel_time buffer).
    """
    sorted_visits = sorted(visits, key=lambda v: to_min(v.start))
    slots: list[dict] = []   # each slot tracks when the agent is free again
    assign: dict[str, int] = {}

    for v in sorted_visits:
        v_start = to_min(v.start)
        best, best_free = -1, -1

        for i, slot in enumerate(slots):
            if slot["free_at"] + travel_time <= v_start and slot["free_at"] > best_free:
                best_free = slot["free_at"]
                best = i

        if best == -1:
            slots.append({"free_at": to_min(v.end)})
            assign[v.id] = len(slots) - 1
        else:
            slots[best]["free_at"] = to_min(v.end)
            assign[v.id] = best

    return len(slots), assign


def interval_scheduling(visits: list[Visit]) -> list[str]:
    """
    Maximum visits a single agent can handle.
    Greedy: sort by finish time, pick each visit that starts after
    the previous one ends.
    """
    sorted_visits = sorted(visits, key=lambda v: to_min(v.end))
    selected: list[str] = []
    last_end = -1

    for v in sorted_visits:
        if to_min(v.start) >= last_end:
            selected.append(v.id)
            last_end = to_min(v.end)

    return selected


def find_property_conflicts(visits: list[Visit]) -> list[dict]:
    """Detect visits to the same property with overlapping times."""
    by_prop: dict[str, list[Visit]] = {}
    for v in visits:
        key = v.property.strip().lower()
        by_prop.setdefault(key, []).append(v)

    conflicts = []
    for group in by_prop.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if to_min(a.start) < to_min(b.end) and to_min(b.start) < to_min(a.end):
                    conflicts.append({
                        "v1": a.model_dump(),
                        "v2": b.model_dump(),
                        "property": a.property,
                    })
    return conflicts


def build_agent_slots(agents: list[Agent], visits: list[Visit], assign: dict[str, int]) -> list[dict]:
    slots = [
        {"id": a.id, "name": a.name, "colorIndex": i % 6, "visits": []}
        for i, a in enumerate(agents)
    ]
    for v in visits:
        idx = assign.get(v.id)
        if idx is not None and idx < len(slots):
            slots[idx]["visits"].append(v.model_dump())
    return slots


def per_agent_scheduling(agent_slots: list[dict]) -> dict[str, list[str]]:
    """Run interval scheduling on each agent's assigned visits."""
    result = {}
    for slot in agent_slots:
        visits = [Visit(**v) for v in slot["visits"]]
        result[slot["id"]] = interval_scheduling(visits)
    return result


# ── Routes ──────────────────────────────────────────────────

@app.get("/")
def serve_frontend():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.post("/api/schedule")
def compute_schedule(req: ScheduleRequest):
    visits = req.visits
    agents = req.agents
    travel_time = req.travelTime

    if not visits:
        return {
            "mode": "empty",
            "minAgents": 0,
            "k": len(agents),
            "agentSlots": [],
            "scheduled": [],
            "unfit": [],
            "conflicts": [],
            "assign": {},
            "maxSingleAgent": [],
        }

    conflicts = find_property_conflicts(visits)
    min_agents, assign = interval_partitioning(visits, travel_time)
    max_single_agent = interval_scheduling(visits)
    k = len(agents)

    if k == 0:
        virtual = [
            Agent(id=f"v{i}", name=f"Corretor {i+1}")
            for i in range(min_agents)
        ]
        agent_slots = build_agent_slots(virtual, visits, assign)
        return {
            "mode": "virtual",
            "minAgents": min_agents,
            "k": k,
            "agentSlots": agent_slots,
            "scheduled": [v.model_dump() for v in visits],
            "unfit": [],
            "conflicts": conflicts,
            "assign": assign,
            "maxSingleAgent": max_single_agent,
            "perAgentScheduling": per_agent_scheduling(agent_slots),
        }

    agent_slots = build_agent_slots(agents, visits, assign)
    mode = "sufficient" if k >= min_agents else "need_more"

    return {
        "mode": mode,
        "minAgents": min_agents,
        "k": k,
        "agentSlots": agent_slots,
        "scheduled": [v.model_dump() for v in visits],
        "unfit": [],
        "conflicts": conflicts,
        "assign": assign,
        "maxSingleAgent": max_single_agent,
        "perAgentScheduling": per_agent_scheduling(agent_slots),
    }
