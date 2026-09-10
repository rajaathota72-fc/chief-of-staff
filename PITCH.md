# Chief of Staff — pitch

## The problem, specifically

A founder's inbox and calendar aren't full of hard decisions. They're full of
*small* decisions that are only easy because the founder has context a system
doesn't: which client always tries to sneak in scope, which investor emails
get same-day replies, that meetings before 9:30am are off-limits. That context
lives in the founder's head, which means it doesn't scale past one person and
doesn't get faster over time — every Monday looks like the last one.

Generic inbox-bots fail here for a specific reason: they're stateless. They
apply the same rules to every founder, forever, and every correction you give
them evaporates the moment the session ends. That's the actual gap.

## Why this isn't just another triage bot

Most "AI inbox assistant" demos show the model reading email once. The thing
worth watching in this project is the **second run**: give it a correction,
run it again on the same kind of scenario, and it behaves differently — not
because you edited a config file, but because it wrote its own memory and
read it back. That loop (decide → get corrected → remember → decide better)
is the actual product. The inbox/calendar triage is just the surface it's
demonstrated on.

## Who it's for

Early-stage founders and solo operators — the people who don't have an EA,
whose calendar and inbox are both "the business," and who lose real hours a
week to work that's genuinely not hard, just constant and context-dependent.

## What the demo needs to prove

1. It can look at a realistic, messy inbox + calendar and make the *right*
   call on routine items without asking.
2. It escalates the right things — money, legal, ambiguity — and gives a
   reason a founder can act on in one glance, not a wall of text.
3. A correction changes its future behavior, visibly, in the same session.
4. It's a real product surface (the web digest), not a terminal transcript.

## Demo video script (~2:30)

**0:00–0:20 — The problem**
Cold open on a cluttered inbox screenshot or a quick voiceover: "Founders
don't need another app to check. They need the busywork gone before they
wake up." State who it's for in one sentence.

**0:20–1:10 — Live triage run**
Open the web UI (`web/app.py`), click **Run today's briefing**. Let the
digest render. Narrate two or three concrete decisions as they appear in the
digest text — e.g. "it declined the cold recruiter outreach, booked the call
with the actual prospect, and left the newsletter alone" — then point at the
**Needs a decision** column: "and it stopped here, on the legal redlines,
because that's not its call to make."

**1:10–2:00 — Teaching it something**
Pick an escalation, click **Correct it**, type a real instruction (e.g. "CC
my cofounder Alex on anything mentioning Delta Corp"). Show the agent's
confirmation. Click **Reset demo data**, then **Run briefing again** — and
show the *same kind of scenario* now getting handled according to the new
rule, without re-explaining it. This is the moment that should land as the
"wow": the agent didn't just do a task, it got measurably better at your job.

**2:00–2:30 — Close**
One sentence on what's real vs. what's next: this runs standalone today, and
is built to deploy on AgentCore Runtime with AgentCore Memory backing the
preference store for a true always-on version — name-drop the specific fit
(`userPreferenceMemoryStrategy` is literally built for this pattern), then
end on the impact line: hours back, every week, without another app to check.

## One-line pitch (for the submission form)

Chief of Staff is a Strands agent that triages a founder's inbox and calendar
end-to-end — replying, scheduling, declining — and only surfaces the handful
of decisions that actually need a human, getting measurably better at the job
every time you correct it.
