"""Instant, offline starting points for a roadmap.

Generation (`advice/roadmap_gen.py`) is the flexible path: it costs an LLM
call and needs the user to already know how to phrase a goal. A template
is the deterministic path - a hand-written step graph a user can apply
with one click and no wait. `TemplateStep.depends_on` deliberately mirrors
`ProposedNode.depends_on` (titles, not ids) so the same layout and
dependency-resolution code in web/api.py handles both without a special
case.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateStep:
    title: str
    detail: str
    depends_on: tuple[str, ...] = ()  # by TITLE, within the same template


@dataclass(frozen=True)
class RoadmapTemplate:
    id: str  # stable kebab-case slug, part of the API contract
    name: str
    description: str  # one line, shown on the card in the UI
    steps: tuple[TemplateStep, ...]


TEMPLATES: tuple[RoadmapTemplate, ...] = (
    RoadmapTemplate(
        id="open-source-contribution",
        name="Open Source Contribution",
        description="Go from zero to a merged pull request on a real project.",
        steps=(
            TemplateStep(
                title="Find a project to contribute to",
                detail=(
                    "Look for an active repo in a language or domain you already "
                    "know, with recent commits and a welcoming contributing guide."
                ),
            ),
            TemplateStep(
                title="Get it building locally",
                detail=(
                    "Clone it, install dependencies, and run the test suite before "
                    "you touch any code, so you know your environment is sound."
                ),
                depends_on=("Find a project to contribute to",),
            ),
            TemplateStep(
                title="Pick a good first issue",
                detail=(
                    "Filter issues labeled 'good first issue' or 'help wanted' for "
                    "something small and well-scoped enough to finish in a sitting."
                ),
                depends_on=("Get it building locally",),
            ),
            TemplateStep(
                title="Discuss your approach on the issue",
                detail=(
                    "Comment with a short plan before writing code, so a maintainer "
                    "can steer you away from a dead end early."
                ),
                depends_on=("Pick a good first issue",),
            ),
            TemplateStep(
                title="Write the change and its tests",
                detail=(
                    "Match the project's existing style and add tests that cover "
                    "the behavior you changed, not just the happy path."
                ),
                depends_on=("Discuss your approach on the issue",),
            ),
            TemplateStep(
                title="Submit the pull request",
                detail=(
                    "Write a clear PR description linking the issue and explaining "
                    "what changed and why, not just what."
                ),
                depends_on=("Write the change and its tests",),
            ),
            TemplateStep(
                title="Respond to review feedback",
                detail=(
                    "Address comments promptly and without defensiveness - review "
                    "back-and-forth is normal, not a sign you did it wrong."
                ),
                depends_on=("Submit the pull request",),
            ),
        ),
    ),
    RoadmapTemplate(
        id="technical-interview-prep",
        name="Technical Interview Prep",
        description="Structured drilling from weak spots to mock interviews.",
        steps=(
            TemplateStep(
                title="Audit your weak areas",
                detail=(
                    "Take a timed practice set across topics and note which ones "
                    "you consistently stall on, so prep time goes where it matters."
                ),
            ),
            TemplateStep(
                title="Drill core data structures",
                detail=(
                    "Rebuild arrays, hash maps, trees, and graphs from memory until "
                    "the operations are automatic, not looked up."
                ),
                depends_on=("Audit your weak areas",),
            ),
            TemplateStep(
                title="Drill common algorithm patterns",
                detail=(
                    "Work through sliding window, two pointers, DFS/BFS, and "
                    "dynamic programming until you recognize the pattern fast."
                ),
                depends_on=("Audit your weak areas",),
            ),
            TemplateStep(
                title="Practice system design basics",
                detail=(
                    "Learn to reason about scale, storage choices, and tradeoffs "
                    "for a handful of classic systems like a URL shortener or feed."
                ),
                depends_on=("Audit your weak areas",),
            ),
            TemplateStep(
                title="Prepare behavioral stories",
                detail=(
                    "Write out three or four STAR-format stories covering conflict, "
                    "failure, and leadership so you're not improvising under stress."
                ),
            ),
            TemplateStep(
                title="Run timed mock interviews",
                detail=(
                    "Do at least three mocks with a peer or platform, talking "
                    "out loud the whole time, not just solving silently."
                ),
                depends_on=(
                    "Drill core data structures",
                    "Drill common algorithm patterns",
                    "Practice system design basics",
                ),
            ),
            TemplateStep(
                title="Debrief and close remaining gaps",
                detail=(
                    "Review what tripped you up in the mocks and drill exactly "
                    "those gaps before the real thing."
                ),
                depends_on=("Run timed mock interviews",),
            ),
        ),
    ),
    RoadmapTemplate(
        id="side-project-launch",
        name="Side Project Launch",
        description="Ship the smallest useful version and see if anyone wants it.",
        steps=(
            TemplateStep(
                title="Define the smallest useful version",
                detail=(
                    "Write down the one thing the project must do to be worth "
                    "using, and cut everything that isn't that."
                ),
            ),
            TemplateStep(
                title="Build the core loop",
                detail=(
                    "Implement just the primary action a user takes, end to end, "
                    "before touching polish, auth, or edge cases."
                ),
                depends_on=("Define the smallest useful version",),
            ),
            TemplateStep(
                title="Deploy it somewhere real",
                detail=(
                    "Put it on a public URL, even if rough, so it's usable by "
                    "someone other than you on your own machine."
                ),
                depends_on=("Build the core loop",),
            ),
            TemplateStep(
                title="Get five people to try it",
                detail=(
                    "Hand it directly to five people who fit the target user and "
                    "watch them use it rather than asking if they'd use it."
                ),
                depends_on=("Deploy it somewhere real",),
            ),
            TemplateStep(
                title="Fix the friction they hit",
                detail=(
                    "Address the specific points where those five people got "
                    "confused or gave up, not hypothetical future features."
                ),
                depends_on=("Get five people to try it",),
            ),
            TemplateStep(
                title="Decide whether to keep going",
                detail=(
                    "Look honestly at whether anyone came back unprompted, and "
                    "decide to invest further, pivot, or shelve it."
                ),
                depends_on=("Fix the friction they hit",),
            ),
        ),
    ),
    RoadmapTemplate(
        id="research-a-topic",
        name="Research a Topic",
        description="Go from an unfamiliar topic to a written synthesis.",
        steps=(
            TemplateStep(
                title="Survey the landscape",
                detail=(
                    "Skim broadly across overviews, talks, and summaries to map "
                    "out the topic's major subareas before going deep on any one."
                ),
            ),
            TemplateStep(
                title="Pick primary sources",
                detail=(
                    "Choose the small set of papers, docs, or books that actually "
                    "matter, based on what kept recurring in the survey."
                ),
                depends_on=("Survey the landscape",),
            ),
            TemplateStep(
                title="Read closely and take structured notes",
                detail=(
                    "Work through each source with notes organized by question, "
                    "not just a linear summary of what it says."
                ),
                depends_on=("Pick primary sources",),
            ),
            TemplateStep(
                title="Identify open questions and disagreements",
                detail=(
                    "Note where sources conflict or where the field itself is "
                    "still unsettled, since that's usually the interesting part."
                ),
                depends_on=("Read closely and take structured notes",),
            ),
            TemplateStep(
                title="Synthesize your own view",
                detail=(
                    "Write a summary in your own words that connects the sources "
                    "instead of listing them, and states where you land."
                ),
                depends_on=("Identify open questions and disagreements",),
            ),
            TemplateStep(
                title="Write it up to share",
                detail=(
                    "Turn the synthesis into something shareable - a doc, post, "
                    "or note - so the effort compounds instead of evaporating."
                ),
                depends_on=("Synthesize your own view",),
            ),
        ),
    ),
    RoadmapTemplate(
        id="job-application-push",
        name="Job Application Push",
        description="A focused sprint from target list to signed offer.",
        steps=(
            TemplateStep(
                title="Build a target company list",
                detail=(
                    "List 20-30 companies you'd actually want to work at, ranked "
                    "by fit, so effort goes toward roles worth getting."
                ),
            ),
            TemplateStep(
                title="Tailor your resume per target",
                detail=(
                    "Adjust the top third of your resume to mirror each target's "
                    "language and priorities rather than sending one generic copy."
                ),
                depends_on=("Build a target company list",),
            ),
            TemplateStep(
                title="Find referrals at target companies",
                detail=(
                    "Search your network and alumni connections for a warm intro "
                    "at each target before applying cold."
                ),
                depends_on=("Build a target company list",),
            ),
            TemplateStep(
                title="Submit applications",
                detail=(
                    "Apply to every target with the tailored resume, referral "
                    "attached where you have one, within a tight window."
                ),
                depends_on=(
                    "Tailor your resume per target",
                    "Find referrals at target companies",
                ),
            ),
            TemplateStep(
                title="Follow up on silence",
                detail=(
                    "Send a short follow-up after a week or two of no response "
                    "instead of assuming silence means rejection."
                ),
                depends_on=("Submit applications",),
            ),
            TemplateStep(
                title="Track and negotiate offers",
                detail=(
                    "Log every response in one place and use competing offers as "
                    "real leverage rather than accepting the first number."
                ),
                depends_on=("Follow up on silence",),
            ),
        ),
    ),
)


def get_template(template_id: str) -> RoadmapTemplate | None:
    return next((t for t in TEMPLATES if t.id == template_id), None)
