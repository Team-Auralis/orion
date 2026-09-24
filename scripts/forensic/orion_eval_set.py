#!/usr/bin/env python3
"""ORION-specific unseen evaluation set (hardcoded, held out from ALL training).

A fixed, frozen set of 40 items (30 open completions + 10 four-option MC) in
the ORION domain. The set is deliberately curated to NOT reference the
training corpus (wikitext-103 / FineWeb-Edu / Pile-uncopyrighted): items are
short trivia / arithmetic / codeish probes written for this repo.

Isolation contract (zero trust, enforced at eval time):
  * Every item must pass the corpus-builder contamination check
    (corpus_builder.check_leak -> 0 hits on BOTH the context and the gold
    answer strings). Items that leak are dropped from scoring; the phrasing
    here was written so all items pass, and tests/test_orion_eval_set.py
    re-asserts that on every run.
  * This file is the grader: it is never tuned against the model's outputs.

Scoring protocol (see scripts/forensic/eval_suite.py):
  * kind == "completion": greedy completion match (normalized) for accuracy
    plus mean-log-prob of the gold continuation as the likelihood score.
  * kind == "mc": 4-option multiple choice, argmax of mean candidate
    continuation log-prob (identical protocol to HellaSwag / ARC / Wino).
"""

ORION_ITEMS: list[dict] = [
    # --- 30 completions: trivia / arithmetic / codeish ----------------------
    {"kind": "completion", "prompt": "The capital city of Nauru is", "answer": "yaren"},
    {
        "kind": "completion",
        "prompt": "The capital city of Tuvalu is",
        "answer": "funafuti",
    },
    {
        "kind": "completion",
        "prompt": "The capital city of Vanuatu is",
        "answer": "port vila",
    },
    {
        "kind": "completion",
        "prompt": "The capital city of Bhutan is",
        "answer": "thimphu",
    },
    {
        "kind": "completion",
        "prompt": "The capital city of Andorra is",
        "answer": "andorra la vella",
    },
    {
        "kind": "completion",
        "prompt": "The capital city of Eswatini is",
        "answer": "mbabane",
    },
    {
        "kind": "completion",
        "prompt": "The capital city of Kyrgyzstan is",
        "answer": "bishkek",
    },
    {
        "kind": "completion",
        "prompt": "The capital city of Moldova is",
        "answer": "chisinau",
    },
    {
        "kind": "completion",
        "prompt": "The capital city of Eritrea is",
        "answer": "asmara",
    },
    {
        "kind": "completion",
        "prompt": "The capital city of Djibouti is",
        "answer": "djibouti",
    },
    {
        "kind": "completion",
        "prompt": "Compute the product of 17 and 23. The answer is",
        "answer": "391",
    },
    {
        "kind": "completion",
        "prompt": "Compute the product of 12 and 18. The answer is",
        "answer": "216",
    },
    {
        "kind": "completion",
        "prompt": "Compute the product of 9 and 14. The answer is",
        "answer": "126",
    },
    {
        "kind": "completion",
        "prompt": "Compute the sum of 137 and 286. The answer is",
        "answer": "423",
    },
    {
        "kind": "completion",
        "prompt": "Compute the sum of 512 and 333. The answer is",
        "answer": "845",
    },
    {
        "kind": "completion",
        "prompt": "Subtract 147 from 500. The result is",
        "answer": "353",
    },
    {
        "kind": "completion",
        "prompt": "Subtract 68 from 200. The result is",
        "answer": "132",
    },
    {
        "kind": "completion",
        "prompt": "Raise 7 to the power of 2. The answer is",
        "answer": "49",
    },
    {
        "kind": "completion",
        "prompt": "Raise 11 to the power of 2. The answer is",
        "answer": "121",
    },
    {
        "kind": "completion",
        "prompt": "Double 64 and then add 12. The answer is",
        "answer": "140",
    },
    {"kind": "completion", "prompt": "Divide 96 by 8. The answer is", "answer": "12"},
    {"kind": "completion", "prompt": "Divide 144 by 12. The answer is", "answer": "12"},
    {"kind": "completion", "prompt": "Multiply 15 by 6. The answer is", "answer": "90"},
    {
        "kind": "completion",
        "prompt": "The number of minutes in three hours is",
        "answer": "180",
    },
    {
        "kind": "completion",
        "prompt": "The number of seconds in ten minutes is",
        "answer": "600",
    },
    {
        "kind": "completion",
        "prompt": "The result of raising 2 to the power of 8 is",
        "answer": "256",
    },
    {
        "kind": "completion",
        "prompt": "In the Python programming language, the function that returns the length of a list is named",
        "answer": "len",
    },
    {
        "kind": "completion",
        "prompt": "In the Python programming language, the keyword used to define a function is",
        "answer": "def",
    },
    {
        "kind": "completion",
        "prompt": "In the Python programming language, the built-in function that writes text to the terminal is named",
        "answer": "print",
    },
    {
        "kind": "completion",
        "prompt": "In the Python programming language, the data structure that stores key value pairs is called a",
        "answer": "dictionary",
    },
    # --- 10 four-option multiple choice ------------------------------------
    {
        "kind": "mc",
        "prompt": "Which planet has the shortest orbital period around the Sun?",
        "options": ["Mercury", "Venus", "Mars", "Jupiter"],
        "answer": 0,
    },
    {
        "kind": "mc",
        "prompt": "Which of these numbers is divisible by 9?",
        "options": ["72", "83", "97", "101"],
        "answer": 0,
    },
    {
        "kind": "mc",
        "prompt": "What is the boiling point of pure water at sea level, in degrees Celsius?",
        "options": ["90", "100", "110", "212"],
        "answer": 1,
    },
    {
        "kind": "mc",
        "prompt": "Which of these is a prime number?",
        "options": ["91", "95", "97", "99"],
        "answer": 2,
    },
    {
        "kind": "mc",
        "prompt": "Which of these is a valid Python variable name?",
        "options": ["2things", "my_var", "my-var", "class"],
        "answer": 1,
    },
    {
        "kind": "mc",
        "prompt": "What is the capital city of Australia?",
        "options": ["Sydney", "Melbourne", "Canberra", "Perth"],
        "answer": 2,
    },
    {
        "kind": "mc",
        "prompt": "Which of these rivers is the longest on Earth?",
        "options": ["Amazon", "Nile", "Mississippi", "Danube"],
        "answer": 1,
    },
    {
        "kind": "mc",
        "prompt": "What is the chemical symbol for the element gold?",
        "options": ["Au", "Ag", "Gd", "Go"],
        "answer": 0,
    },
    {
        "kind": "mc",
        "prompt": "How many bits are contained in one byte?",
        "options": ["4", "8", "16", "32"],
        "answer": 1,
    },
    {
        "kind": "mc",
        "prompt": "Which of these abstract data types is last-in first-out?",
        "options": ["Queue", "Stack", "Heap", "Array"],
        "answer": 1,
    },
]

ORION_CHANCE_PER_ITEM = {
    "completion": 1.0 / 10240.0,  # uniform next-token gold match over the BPE vocab
    "mc": 0.25,
}


def orion_probe_text(item: dict) -> str:
    """Contamination screening string for an ORION item (context + gold)."""
    if item["kind"] == "completion":
        return item["prompt"] + " " + item["answer"]
    return item["prompt"] + " " + item["options"][item["answer"]]
