# Rules for new emotion-series scripts (weekly batch)

The weekly writer adds **7 new scripts** as `content/generated/YYYY-MM-DD.md`, then runs
`python3 -m mnemabot.validate` and fixes every PROBLEM before pushing.

Read first: `content/EMOTION_SERIES_EN.md` (the original 60, by the account owner). The new ones
must sound like they came from the same writer. Read the 60 for voice, rhythm and length.
Don't paraphrase them.

## Format (exact — the renderer parses it)

```
# CLUSTER 1 · FEAR & ANXIETY  `#4A7EC0`

### 61 Overwhelm — hook C
- **HOOK** If every message feels like one more thing on a full plate—
- **TURN** you're not bad at coping.
- **NAME** Overwhelm wants a smaller next step, not a bigger effort.
- **LINE** "I can't see where to start."
- **DO** Pick the smallest thing on the list. Do only that. Then decide again.
- **LOOP** optional, one short line
```

- Every script sits under a `# CLUSTER` header. Use only these five, with these exact colours:
  - `# CLUSTER 1 · FEAR & ANXIETY  `#4A7EC0``
  - `# CLUSTER 2 · SHAME & SELF-WORTH  `#A85455``
  - `# CLUSTER 3 · CONFUSION & NUMBNESS  `#6E6A8C``
  - `# CLUSTER 4 · SADNESS & DEPLETION  `#3E4C7A``
  - `# CLUSTER 5 · ANGER & BOUNDARIES  `#B5663C``
- Numbering continues from the `next_number` that validate prints. Never reuse a number.
- The emotion name must not already exist, case-insensitive. A new angle on an existing emotion is
  fine if the name is distinct, e.g. "Sunday dread" or "Anxiety at 3am".
- HOOK, TURN, NAME, LINE and DO are required, each ≤ 26 words (they are read aloud and shown word by word).
  LOOP is optional.
- LINE is the sentence the emotion is actually saying. Usually first person, in straight double quotes.

## Hook rotation

A misread flip · B sentence completion · C scene call-out · D correct a phrase · E question.
Continue the A→C→D→B→E cycle from the last script in the library, and never put two of the same
type in a row. Put the type in the heading: `— hook C`.

## Content rules (non-negotiable)

- This is psychoeducation in plain words, not clinical advice. No diagnosis or disorder names, no
  therapy or treatment claims, no pop-neuroscience (amygdala, dopamine, cortisol…). `validate` blocks
  the obvious words.
- DO is one concrete thing someone can do in about 60 seconds, alone, for free.
- Don't write about despair, grief, suicide, self-harm, abuse, trauma or eating. Those need a
  helpline card and human review, so they stay out of the automated queue.
- Don't mention Mnema or any app in the script. The video adds the product at the end.
- Don't quote real people, songs, books or other creators.
- Spread each batch across at least 3 clusters, and lean towards everyday, relatable moments
  (work, texts, sleep, comparison, family, rest).

## Batch size and queue

- Write 7 per batch. If validate shows `unposted` ≥ 30, skip writing this week.
- New scripts go to the back of the queue automatically. Nothing else needs to change.
