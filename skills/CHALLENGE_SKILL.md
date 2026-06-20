---
name: challenge-skill
description: >
  Revenue Manager skill-pack manifest and version pin (otel-rm-v2). Index of the on-demand
  skills this agent loads to answer hotel GM revenue questions using the five tools
  get_otb_summary, get_segment_mix, get_pickup_delta, get_as_of_otb, get_block_vs_transient_mix.
---

# Revenue Manager skill pack — `otel-rm-v2`

This pack encodes how an experienced hotel revenue manager interprets reservation data and
turns it into commercial judgment for a General Manager. Skills load on demand (progressive
disclosure); each routes to the tested tool layer and never improvises SQL.

| Skill | Loads for | Primary tool(s) | Judgment? |
|-------|-----------|-----------------|-----------|
| `otb-summary` | "what's on the books for <month>?" | `get_otb_summary` | no (routing) |
| `segment-mix` | "what's driving <month>?", mix, share | `get_segment_mix` | light |
| `pickup-pace` | "what changed recently?", pace | `get_pickup_delta` | **yes** |
| `ota-dependency` | "are we too dependent on OTA?" | `get_segment_mix` | **yes** |
| `group-block-concentration` | "concentrated in big bookings?" | `get_block_vs_transient_mix` | **yes** |
| `point-in-time-otb` | "what did the book look like on <date>?" | `get_as_of_otb` (HITL) | no (routing) |
| `grain-and-filter-guardrails` | every answer (avoid traps) | all five | guardrail |

Answer style: lead with the headline number, name the drivers, quantify, flag the risk, and
recommend an action — like a sharp morning briefing, not a dashboard read-out.
