#!/usr/bin/env python3
"""Random topic seed for evolutionary-explainer videos (Thought Vortex style).

Usage:
  python3 scripts/suggest_topic.py          # one random seed (stdout)
  python3 scripts/suggest_topic.py --count 5

The assistant uses this output + .cursor/skills/evolutionary-explainer-topics/
to craft a single question title. Randomness lives here — not in a fixed list order.
"""
from __future__ import annotations

import argparse
import json
import random
import sys

_rng = random.SystemRandom()

HOOKS: list[dict[str, str]] = [
    {"id": "accidentally_created", "label": "accidentally created", "template": "How Did Humans Accidentally Create {seed}?"},
    {"id": "why_weird", "label": "why we're weird", "template": "Why Are Humans So {seed}?"},
    {"id": "why_do", "label": "why we do X", "template": "Why Do Humans {seed}?"},
    {"id": "role_reversal", "label": "role reversal", "template": "Did {seed} Really Domesticate Humans?"},
    {"id": "survival_shock", "label": "survival shock", "template": "Why Did Most Ancient Humans {seed}?"},
    {"id": "scarcity", "label": "scarcity craving", "template": "Why Would Your Ancestors Kill for {seed}?"},
    {"id": "ancient_how", "label": "ancient humans how", "template": "How Did Ancient Humans {seed}?"},
    {"id": "ancient_think", "label": "ancient beliefs", "template": "What Did Ancient Humans Think {seed} Was?"},
    {"id": "tribal_social", "label": "tribal social", "template": "What Happened to the {seed} Person in the Tribe?"},
    {"id": "body_weird", "label": "body mystery", "template": "Why Are Human {seed} So Weird?"},
]

SEEDS: dict[str, list[str]] = {
    "accidentally_created": [
        "Cooking", "Storytelling", "Laughter", "Taboos", "Agriculture",
        "Music", "Language", "Gossip", "Boredom", "Fire Rituals",
    ],
    "why_weird": [
        "Obsessed With Cute Things", "Bad at Being Alone", "Loud When Happy",
        "Attached to Objects", "Terrified of the Dark", "Unable to Do Nothing",
    ],
    "why_do": [
        "Want to Pet Everything", "Need Hugs", "Cry When They're Happy",
        "Name Everything", "Stare at Fire", "Boredom-Eat", "Groom Each Other",
    ],
    "role_reversal": [
        "Cats", "Cows", "Grain", "Houses", "Boredom", "Sugar", "Coffee",
    ],
    "survival_shock": [
        "Die Before 30", "Never Meet Their Grandparents", "Fear the Dark",
        "Sleep in Shifts", "Share Beds With Strangers", "Eat So Little",
    ],
    "scarcity": [
        "Salt", "Sugar", "Fat", "Honey", "Clean Water", "Warmth", "Meat",
    ],
    "ancient_how": [
        "Mate", "Choose a Partner", "Know Who Was Family", "Deal With Jealousy",
        "Handle the Dead", "Wake Up Before Alarms", "Stay Warm",
    ],
    "ancient_think": [
        "Thunder", "Dreams", "Death", "Eclipses", "Mirrors", "Mountains",
    ],
    "tribal_social": [
        "Laziest", "Worst", "Strangest", "Quietest", "Most Useless",
    ],
    "body_weird": [
        "Babies", "Teeth", "Feet", "Backs", "Gut Feelings", "Hangovers",
    ],
}


def pick_seed() -> dict[str, str]:
    hook = _rng.choice(HOOKS)
    pool = SEEDS[hook["id"]]
    seed = _rng.choice(pool)
    title_hint = hook["template"].format(seed=seed)
    return {
        "hook": hook["label"],
        "hook_id": hook["id"],
        "seed": seed,
        "title_hint": title_hint,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Random evolutionary-explainer topic seed")
    parser.add_argument("--count", type=int, default=1, help="Number of seeds (default 1)")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()
    count = max(1, min(args.count, 20))
    picks = [pick_seed() for _ in range(count)]

    if args.json:
        print(json.dumps(picks if count > 1 else picks[0], indent=2))
        return 0

    if count == 1:
        p = picks[0]
        print(f"hook: {p['hook']}")
        print(f"seed: {p['seed']}")
        print(f"title_hint: {p['title_hint']}")
        print("(Craft a polished question title from this seed — do not copy verbatim if awkward.)")
    else:
        for i, p in enumerate(picks, 1):
            print(f"{i}. [{p['hook']}] {p['title_hint']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
