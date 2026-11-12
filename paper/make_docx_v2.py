"""Build paper/AH2027_v2.docx: the Augmented Humans 2027 short paper.

    python paper/make_docx_v2.py /path/to/acm_submission_template.docx               # with the authors' names
    python paper/make_docx_v2.py /path/to/acm_submission_template.docx --anonymous   # AH2027_v2_anonymous.docx
    python paper/make_docx_v2.py /path/to/acm_submission_template.docx --gdocs       # AH2027_v2_gdocs.docx, for Google Docs

The conference reviews double-blind, so the copy uploaded for review must be the anonymous one.

Reuses the helpers in make_docx.py (template styles, figures, tables). The course report
(Report.docx) is not touched.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import make_docx as base
from make_docx import bib, figure, formula, head1, head2, p, paras, table

base.OUT = base.HERE / "AH2027_v2.docx"


REFS = [
    ("apple", "Apple Inc. 2024. Apple Announces New Accessibility Features, Including Eye Tracking. Apple Newsroom. https://www.apple.com/newsroom/2024/05/apple-announces-new-accessibility-features-including-eye-tracking/"),
    ("brooke", "John Brooke. 1996. SUS: A “Quick and Dirty” Usability Scale. In *Usability Evaluation in Industry*. Taylor & Francis, 189-194."),
    ("cha", "Y. Cha, D. Chun, and S. Park. 2026. iPhoneme: Brain-to-Text Communication for ALS Using ConformerXL Decoding. arXiv:2604.16441."),
    ("jacob", "Robert J. K. Jacob. 1990. What You Look at is What You Get: Eye Movement-Based Interaction Techniques. In *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems* (CHI ’90). ACM, 11-18. https://doi.org/10.1145/97243.97246"),
    ("li", "Lihong Li, Wei Chu, John Langford, and Robert E. Schapire. 2010. A Contextual-Bandit Approach to Personalized News Article Recommendation. In *Proceedings of the 19th International Conference on World Wide Web* (WWW ’10). ACM, 661-670. https://doi.org/10.1145/1772690.1772758"),
    ("majaranta", "Päivi Majaranta, Ulla-Kaija Ahola, and Oleg Špakov. 2009. Fast Gaze Typing with an Adjustable Dwell Time. In *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems* (CHI ’09). ACM, 357-360. https://doi.org/10.1145/1518701.1518758"),
    ("manzoni", "M. Manzoni, Dragan Ahmetovic, and Sergio Mascetti. 2024. Personalized Facial Gesture Recognition for Accessible Mobile Gaming. In *Computers Helping People with Special Needs* (ICCHP 2024). Springer, 120-127. https://doi.org/10.1007/978-3-031-62846-7_15"),
    ("meena", "Yogesh Kumar Meena and M. Salvi. 2025. Multimodal Appearance-Based Gaze-Controlled Virtual Keyboard with Synchronous-Asynchronous Interaction for Low-Resource Settings. https://doi.org/10.48550/arXiv.2508.16606"),
    ("mott", "Martez E. Mott, Shane Williams, Jacob O. Wobbrock, and Meredith Ringel Morris. 2017. Improving Dwell-Based Gaze Typing with Dynamic, Cascading Dwell Times. In *Proceedings of the 2017 CHI Conference on Human Factors in Computing Systems* (CHI ’17). ACM. https://doi.org/10.1145/3025453.3025517"),
    ("namnakani", "Omar Namnakani, Yasmeen Abdrabou, Jonathan Grizou, and Mohamed Khamis. 2025. GazeBlend: Exploring Paired Gaze-Based Input Techniques for Navigation and Selection Tasks on Mobile Devices. arXiv:2512.15491."),
    ("narkar", "Anish S. Narkar, Jan J. Michalak, Candace E. Peacock, and Brendan David-John. 2024. GazeIntent: Adapting Dwell-Time Selection in VR Interaction with Real-Time Intent Modeling. arXiv:2404.13829."),
    ("paulus", "Yesaya Tommy Paulus and Gerard Bastiaan Remijn. 2021. Usability of Various Dwell Times for Eye-Gaze-Based Object Selection with Eye Tracking. *Displays* 67 (2021), 101997. https://doi.org/10.1016/j.displa.2021.101997"),
    ("severitt", "Björn R. Severitt, Nora Castner, Yannick Sauer, and Siegfried Wahl. 2026. A Real-Time Error Prevention System for Gaze-Based Interaction in Virtual Reality Based on Anomaly Detection. arXiv:2601.15146."),
    ("soukoreff", "R. William Soukoreff and I. Scott MacKenzie. 2003. Metrics for Text Entry Research: An Evaluation of MSD and KSPC, and a New Unified Error Metric. In *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems* (CHI ’03). ACM, 113-120. https://doi.org/10.1145/642611.642632"),
    ("thompson", "William R. Thompson. 1933. On the Likelihood that One Unknown Probability Exceeds Another in View of the Evidence of Two Samples. *Biometrika* 25, 3/4 (1933), 285-294."),
    ("webaim", "WebAIM. 2013. Survey of Users with Motor Disabilities. https://webaim.org/projects/motordisabilitysurvey/"),
    ("wobbrock", "Jacob O. Wobbrock, Shaun K. Kane, Krzysztof Z. Gajos, Susumu Harada, and Jon Froehlich. 2011. Ability-Based Design: Concept, Principles and Examples. *ACM Transactions on Accessible Computing* 3, 3 (2011). https://doi.org/10.1145/1952383.1952384"),
    ("zhang26", "S. Zhang, Y. Gu, Kirsten Cater, and Oussama Metatla. 2026. Beyond Accuracy: Auditing Allocative Harms in Facial-Gesture Recognition for People with Motor Impairments. In *Proceedings of the 2026 CHI Conference on Human Factors in Computing Systems* (CHI ’26). ACM. https://doi.org/10.1145/3772318.3791927"),
    ("zhang17", "Xiaoyi Zhang, Harish Kulkarni, and Meredith Ringel Morris. 2017. Smartphone-Based Gaze Gesture Communication for People with Motor Disabilities. In *Proceedings of the 2017 CHI Conference on Human Factors in Computing Systems* (CHI ’17). ACM, 2878-2889. https://doi.org/10.1145/3025453.3025790"),
]
N = {key: i for i, (key, _) in enumerate(REFS, 1)}      # alphabetical order, as ACM numbers references


def c(*keys: str) -> str:
    """A citation such as [4, 9]."""
    return "[" + ", ".join(str(n) for n in sorted(N[k] for k in keys)) + "]"


AUTHORS = ("Vandya Bisaria", "Mansie Singh", "Sinngam Khaidem")
AFFILIATION = "Indian Institute of Technology Gandhinagar, India"
CITED_AS = "Vandya Bisaria, Mansie Singh, and Sinngam Khaidem"
ANONYMOUS = "--anonymous" in sys.argv
base.GDOCS = "--gdocs" in sys.argv

TITLE = "Communic-aid"
SUBTITLE = "Adapting Dwell Time and Confirmation in Gaze-Based Messaging with a Commodity iPhone"


def build_body() -> str:
    b = []
    b.append(p("Titledocument", TITLE))
    b.append(p("Subtitle", SUBTITLE))
    if ANONYMOUS:
        b.append(p("Authors", "Anonymous Author(s)"))
        b.append(p("Affiliation", "Anonymous Institution"))
    else:
        for name in AUTHORS:
            b.append(p("Authors", name))
            b.append(p("Affiliation", AFFILIATION))
    b.append(p("Abstract", " ".join("""
        People with severe motor impairments often keep control of their eyes long after other movement is
        lost, but gaze interfaces force one trade off on every action: a long dwell is slow, a short dwell
        selects things by mistake, and a fixed confirmation step is either too weak for a call or too
        tedious for a letter. We present Communic-aid, a hands-free messaging system whose only sensor is
        an iPhone with a TrueDepth camera. The phone streams gaze, head pose, blinks, eyebrow raises and a
        spoken confirmation word to a computer that runs a chat app with messages, calls and a gaze
        keyboard. Its central idea is that the interface should learn how much evidence to ask for before
        it acts, per person, per context and per level of risk. Every action belongs to one of four risk
        tiers with an accident cost; a dwell learner sets the dwell from implicit feedback such as undos,
        abandoned looks and stray glances, and a contextual bandit chooses which confirmation signal, if
        any, to ask for on risky actions. In a preliminary study with two able-bodied participants, the
        learner shortened the dwell from 1500 ms to about 1200 ms within one session, with two accidents
        in 146 selections, both on undoable letters and none on risky actions; the router adapted its
        choice of signal to each participant; and a grouped keyboard with large targets was 1.5 to 2.8
        times faster than QWERTY. We discuss what this means for gaze interaction on commodity hardware and
        describe the planned comparison against a fixed baseline, including a participant with a motor
        impairment.
        """.split())))
    b.append('<w:p><w:pPr><w:pStyle w:val="CCSDescription"/></w:pPr><w:r><w:rPr><w:rStyle w:val="CCSHeadchar"/></w:rPr>'
             '<w:t xml:space="preserve">CCS CONCEPTS </w:t></w:r><w:r><w:t xml:space="preserve">• </w:t></w:r><w:r><w:rPr><w:b w:val="0"/></w:rPr>'
             '<w:t>Human-centered computing → Accessibility technologies • Human-centered computing → Interaction techniques</w:t></w:r></w:p>')
    b.append('<w:p><w:pPr><w:pStyle w:val="KeyWords"/></w:pPr><w:r><w:rPr><w:rStyle w:val="KeyWordHeadchar"/><w:b/></w:rPr>'
             '<w:t xml:space="preserve">Additional Keywords and Phrases: </w:t></w:r><w:r><w:t>gaze interaction, adaptive dwell time, '
             'multimodal confirmation, contextual bandit, motor impairment, assistive technology, commodity hardware</w:t></w:r></w:p>')
    b.append(p("ACMRefHead", "ACM Reference Format:"))
    b.append(p("ACMRef", f"{'Anonymous Author(s)' if ANONYMOUS else CITED_AS}. 2027. {TITLE}: {SUBTITLE}. In *Augmented Humans International "
                         "Conference 2027 (AH ’27)*. ACM, New York, NY, USA."))

    # 1 Introduction
    b.append(head1("Introduction"))
    b.append(paras(f"""
        For many people with ALS, muscular dystrophy, cerebral palsy or spinal cord injury, the eyes remain
        controllable long after the hands. Gaze interfaces build on this, but they inherit the Midas touch
        problem {c("jacob")}: the eyes are always looking at something, so the interface cannot tell a look
        that means “do this” from a look that means “I am reading”. The standard remedy is a *dwell* time:
        a button is selected only after the eyes have stayed on it long enough. A long dwell is safe and
        slow; a short dwell is fast and causes accidental selections. Both kinds of error hurt, but not
        equally. An accidental letter costs one backspace. An accidental call or deletion costs far more.

        Existing systems address parts of this. Adaptive dwell methods adjust one threshold to the person
        {c("majaranta", "mott", "narkar")}, and multimodal methods add a second channel to confirm a selection
        {c("cha", "namnakani")}. Our review of this literature found three gaps. First, confirmation is uniform:
        cheap and costly actions face the same bar. Second, adaptive dwell methods mostly learn from explicit
        signals and treat a false selection and a missed selection as equally bad. Third, no system we found
        chooses the confirmation modality itself from experience, although people differ greatly in which
        signals they can produce reliably {c("severitt", "zhang26")}. Dedicated eye trackers also remain costly
        and obtrusive {c("zhang17", "meena")}.

        Communic-aid treats these as one question: *how much evidence should the interface ask for before it
        acts?* It answers per person, per context and per level of risk, and it learns the answer from
        ordinary use, without asking for ratings. In doing so it augments a person’s ability to communicate
        with a device they may already own. Our contributions are:
        """))
    for label, text in [
        ("C1.", "A hands-free messaging system whose only sensor is an iPhone with a TrueDepth camera, combining gaze or head pointing with four confirmation signals: blink and hold, raised eyebrows, a spoken “go”, and an optional switch."),
        ("C2.", "Risk tiers that give every action an accident cost, so the strength of confirmation scales with what an error would cost."),
        ("C3.", "Two learners driven only by implicit feedback: a dwell learner that lengthens the dwell quickly after accidents and shortens it slowly, and a contextual bandit that ranks confirmation signals from past interactions."),
        ("C4.", "A preliminary study with two participants, showing how the learners behave in practice, and a plan for the comparison against a fixed baseline."),
    ]:
        b.append(p("Para", f"**{label}** {text}"))

    # 2 Related work
    b.append(head1("Related Work"))
    b.append(paras(f"""
        **Dwell and the Midas touch.** Dwell selection is the default for gaze input, and the right dwell
        depends on the person and the task {c("paulus")}. Majaranta et al. let typists adjust the dwell
        themselves and saw speed rise with practice {c("majaranta")}. Mott et al. varied the dwell per key
        with the probability of the next letter {c("mott")}. GazeIntent adapts the dwell with a learned model
        of intent, and most returning users preferred the personalised version {c("narkar")}. These methods
        tune one threshold for every action, and most learn from explicit corrections. Communic-aid learns
        from implicit outcomes and weighs accidents by the cost of the action.

        **Second signals.** Pairing gaze with another channel reduces accidental selections: silent speech
        for people with ALS {c("cha")}, gestures paired with dwell on mobile devices {c("namnakani")}, and
        anomaly detection that stops likely errors {c("severitt")}. Facial gestures can be personalised
        {c("manzoni")}, but recognisers show accuracy gaps for people with motor impairments {c("zhang26")}.
        This argues against fixing one confirmation signal in advance, and for choosing it from what works
        for each person, in the spirit of ability-based design {c("wobbrock")}.

        **Commodity hardware.** GazeSpeak showed that a smartphone camera can support gaze gesture
        communication for people with motor disabilities {c("zhang17")}, and webcam keyboards bring gaze
        typing to low resource settings {c("meena")}. Since 2024, iOS also offers system eye tracking with
        dwell control {c("apple")}. Communic-aid uses the phone differently: as a sensor that streams gaze,
        head pose, facial blendshapes and speech to a larger screen, so that one device provides both
        pointing and several confirmation signals, and the decisions run in software that can learn.
        """))

    # 3 Formative input
    b.append(head1("Formative Input"))
    b.append(paras(f"""
        We interviewed three people with motor impairments (muscular dystrophy, cerebral palsy, and a
        locomotor disability) using structured questions adapted from the WebAIM survey {c("webaim")}.
        Together with the literature, the interviews shaped five requirements: (R1) avoid accidental
        actions, above all calls and deletions; (R2) adapt to the individual rather than an average user;
        (R3) use a second modality for confirmation, but sparingly, since too many confirmations are tiring;
        (R4) keep the setup cheap and unobtrusive; and (R5) tolerate involuntary movement and atypical
        speech. One interviewee already sent voice notes instead of long texts because typing took too long,
        and found dictation unreliable with slurred speech, which led us to treat typing effort as a primary
        cost and to listen for a single word rather than dictation.
        """))

    # 4 System
    b.append(head1("System"))
    b.append(figure("architecture.png", 1.0, 1,
                    "Architecture. The iPhone only senses, the core on the computer makes every decision, and the "
                    "browser only draws. The dashed arrow is the learning loop: outcomes update the policy.",
                    "Block diagram: the iPhone sends face frames and a spoken confirmation over UDP to a Python core "
                    "with modules for input, signals, context, interaction, policy, outcomes, chat and persistence, "
                    "which talks to a browser view over a WebSocket."))
    b.append(head2("Sensing with one phone"))
    b.append(paras("""
        The phone sits below the screen, 40 to 60 cm from the face (Figure 1). An iOS app built on ARKit face
        tracking sends, at 60 Hz over UDP, the gaze ray and eye position in camera space, the direction of
        the nose, and the blink and eyebrow blendshapes. On-device speech recognition listens only for the
        word “go”. A Python core on the computer maps the gaze ray to the screen with a nine point
        calibration (quadratic least squares with a small ridge term), smooths it with an exponential filter,
        holds it still during blinks, and corrects slow drift from the centres of buttons just selected. In
        head pointing mode it uses the nose direction instead. A one time signal check measures each
        person’s rest and peak levels and sets each threshold halfway between them (blink held 500 ms,
        eyebrows raised 300 ms). A browser draws the interface and knows no rules. No data leaves the two
        devices.
        """))
    b.append(head2("Risk tiers"))
    b.append(paras("Every action belongs to one of four tiers whose accident cost doubles with each step (Table 1). Both learners use this cost (R1)."))
    b.append(table(1, "Risk tiers. Tier 0 and 1 fire on the learned dwell; tier 2 and 3 add a confirmation step after a fixed 1000 ms dwell.",
                   [600, 3840, 700, 3500],
                   [["Tier", "Actions", "Cost", "Confirmation"],
                    ["0", "Open a chat, back, scroll, navigation", "1", "Learned dwell"],
                    ["1", "Letters, word suggestions, Space, Backspace, settings", "2", "Learned dwell"],
                    ["2", "Send, react, end a call", "4", "Router: dwell alone or a signal"],
                    ["3", "Call, delete, forward", "8", "Always a signal chosen by the router"]]))
    b.append(head2("Labelling outcomes without asking"))
    b.append(paras("""
        The learners never ask for feedback. Instead, the core labels each look and each confirmation
        request from what the person does next (Table 2). Statistics are kept per context group: rested or
        tired (over 20 minutes in, or evening) crossed with steady or shaky gaze (recent gaze spread over 1.5
        times a steady baseline). Until a group has enough data of its own, it borrows the pooled data of all
        groups.
        """))
    b.append(table(2, "Implicit outcomes: how each event is labelled, and what it tells the learners.", [1500, 3900, 3240],
                   [["Outcome", "Rule", "What it tells the learner"],
                    ["Accident", "A selection undone within 5 s, or a letter deleted within 3 s", "The dwell was too short"],
                    ["Worked", "A selection that was not undone", "The dwell was long enough"],
                    ["Give-up", "A look filled at least half the dwell, then the same button was chosen afresh within 5 s", "The dwell was too long"],
                    ["Stray glance", "Any other look that did not fill", "Normal reading; how long glances last"],
                    ["Blocked", "A confirmation request timed out with no attempt", "The check stopped an unwanted action"]]))
    b.append(head2("Dwell learner"))
    b.append(paras(f"""
        For tiers 0 and 1, the learner keeps counts of intended and unintended looks, stray glances and their
        length, and give-ups and the waiting time. From these it draws by Thompson sampling {c("thompson")} the
        probability *π* that a look is intended, a mean stray glance length *g* and a mean patience *p*, and
        scores each dwell *d* from 800 to 2000 ms:
        """))
    b.append(formula("*V*(*d*) = *π* [ (1 − *G*(*d*)) (1 − *λd*) + *r*~give-up~ *G*(*d*) ] − (1 − *π*) *A*(*d*) *c*~tier~",
                     r"V(d) = \pi\,\left[\,(1 - G(d))\,(1 - \lambda d) + r_{\mathrm{give\,up}}\,G(d)\,\right] - (1 - \pi)\,A(d)\,c_{\mathrm{tier}}"))
    b.append(paras("""
        with *A*(*d*) = e^^−d/g^^ the chance a stray glance fires, *G*(*d*) = 1 − e^^−d/p^^ the chance the
        person gives up first, *λ* = 0.6 per second and *r*~give-up~ = −0.5. In words: a longer dwell stops
        more stray glances from firing, but makes the person wait and sometimes give up; the learner picks the
        dwell with the best balance, and a higher tier cost pushes it towards caution. The best *d* is a
        target, not a setting: after each selection the dwell moves 5% towards it, by at most 10 ms when
        shortening and up to 100 ms when lengthening, so accidents are corrected quickly while speed is gained
        cautiously. The dwell starts at 1500 ms and holds for 20 selections per group.
        """, first=False))
    b.append(head2("Modality router"))
    b.append(paras(f"""
        For tiers 2 and 3, a contextual bandit {c("li")} chooses the confirmation step. The arms are dwell alone
        (tier 2 only), blink and hold, raised eyebrows, “go”, and a switch. For each arm, tier and group it
        counts worked, give-up, blocked and accident outcomes, samples their probabilities from a Dirichlet
        distribution and asks for the arm with the highest expected reward. A worked signal earns 1 minus its
        effort, which grows with the person’s time to produce it; a blocked accident earns a small reward
        proportional to the tier cost; an accident costs the full tier cost. The person’s preferred signal
        starts with a bonus, and a group borrows pooled counts until it has 20 tries. Because sampling keeps
        some uncertainty, a signal that worked poorly early on is still tried occasionally rather than ruled
        out for good (R2, R3).
        """))
    b.append(head2("Interface"))
    b.append(figure("screens.png", 0.92, 2,
                    "Screens of the working prototype. In (f) the Delete button has filled and shows the closed eye: it "
                    "waits for blink and hold before it deletes.",
                    "Six screenshots of a dark interface with large buttons: chat list, thread, compose with letter "
                    "groups, the second letter step, message actions, and Delete filled red with a closed eye icon."))
    b.append(paras("""
        The view is a full screen chat app with chats, threads, calls, message actions and settings
        (Figure 2). A look fills the button it rests on; tier 2 and 3 buttons have amber and red outlines, and
        a confirmation request shows the icon of the signal it waits for. A wrong signal shakes the button,
        and an undo strip appears for 5 s after every action. Text entry offers a grouped keyboard with eight
        large letter groups, where a letter takes two selections, and a QWERTY keyboard with one selection per
        letter; both show word suggestions and quick replies. Contacts, chats and replies are simulated from a
        local file.
        """))

    # 5 Preliminary study
    b.append(head1("Preliminary Study"))
    b.append(paras(f"""
        Two able-bodied adults (P1, P2) used the system with gaze pointing in the adaptive condition, in a
        quiet room, with the phone mounted below a laptop screen and their heads free to move. After the
        signal check and calibration, each used the app freely and completed four tasks: navigating between
        chats and settings and changing the preferred signal, composing and sending a message of at least ten
        letters, making and ending a call, and deleting a message. Free use lasted 9 minutes for P1 and 24
        for P2. Each then did a typing test: copying a 248 character passage for two minutes, without word
        suggestions, three times with each keyboard, grouped first, with a new passage each run. We report
        words per minute, accuracy from the edit distance to the passage, and keystrokes per character
        {c("soukoreff")}, all computed from the core’s event log, together with the System Usability Scale
        {c("brooke")} and open feedback.
        """))

    # 6 Results
    b.append(head1("Results"))
    b.append(table(3, "Free use session, from the event log. Selections exclude undo and redo.", [4440, 2100, 2100],
                   [["Measure", "P1", "P2"],
                    ["Session length", "9 min", "24 min"],
                    ["Calibration error", "80 px", "69 px"],
                    ["Selections (tier 0 / 1 / 2 / 3)", "51 (18 / 29 / 2 / 2)", "95 (32 / 51 / 7 / 5)"],
                    ["Accidents", "2 (both tier 1, both undone)", "0"],
                    ["Dwell give-ups", "6", "11"],
                    ["Stray glances", "145", "541"],
                    ["Confirmation requests on tiers 2 and 3 (worked / gave up)", "5 (4 / 1)", "13 (12 / 1)"],
                    ["Dwell at end, tier 0 / tier 1", "1216 / 1333 ms", "1219 / 1431 ms"],
                    ["Head movement, median / 95th percentile", "18 / 214 mm", "18 / 69 mm"]]))
    b.append(paras("""
        **Accidents and confirmation.** Across 146 selections there were two accidents, both letters, both
        undone (Table 3). No tier 2 or 3 action fired by mistake. 16 of 18 confirmation requests succeeded.
        The router adapted within each session. When P1 gave up on raised eyebrows to confirm Send, the next
        Send asked for blink and hold, which worked, as did the call and the deletion that followed. P2 began
        with blink and hold; after three successful confirmations, the router accepted dwell alone on four tier
        2 actions, all of which worked, and after P2 made “go” the preferred signal, P2 confirmed it five times
        out of five. Both participants kept their heads free: typical head movement was 18 mm.

        **Dwell learning.** Stray glances outnumbered selections three to six times, so the interface collects
        much implicit evidence even when nothing is selected. After its warm-up the learner shortened both
        tiers steadily (Figure 3). Tier 0 fell from 1500 to about 1220 ms for both participants. Tier 1 stayed
        longer, as expected from its higher cost. A new context group (P1, tired with shaky gaze) started from
        1500 ms and was learned separately.
        """))
    b.append(figure("dwell_p1.png", 0.78, 3,
                    "P1’s dwell over all sessions, one panel per context group, one line per tier. The first session is "
                    "free use, then three grouped and three QWERTY typing runs. Shading marks the warm-up; marks at the "
                    "bottom are selections (light) and accidents (dark).",
                    "Two step plots of dwell against selection count, each falling from 1500 ms after a warm-up."))
    b.append(paras("""
        **Typing.** The grouped keyboard was 1.5 (P1) and 2.8 (P2) times faster than QWERTY (Table 4), despite
        almost two selections per letter, and not because of the dwell, which was slightly shorter in the
        QWERTY runs. Target size explains it: a letter group was 316 × 113 px and a QWERTY key 113 × 67 px,
        while the calibration error was 69 to 80 px, about one QWERTY key.
        """, first=False))
    b.append(table(4, "Typing test, mean of three two minute runs per keyboard. The dwell was still learning during this test, so the mean tier 1 dwell in use is shown.",
                   [800, 1400, 1300, 1500, 2140, 1500],
                   [["", "Keyboard", "WPM", "Accuracy", "Keystrokes per char.", "Mean dwell"],
                    ["P1", "Grouped", "2.23", "100%", "1.84", "1261 ms"],
                    ["", "QWERTY", "1.50", "91.7%", "1.06", "1214 ms"],
                    ["P2", "Grouped", "1.60", "100%", "1.86", "1327 ms"],
                    ["", "QWERTY", "0.57", "100%", "1.11", "1259 ms"]]))
    b.append(paras("""
        **Usability and feedback.** SUS scores were {{P1 SUS}} (P1) and {{P2 SUS}} (P2), against an average of
        about 68. {{what P1 and P2 said: what worked, what was hard, what they would change}}
        """, first=False))

    # 7 Discussion
    b.append(head1("Discussion"))
    b.append(paras("""
        **Scaling evidence with risk.** The two accidents both fell on letters, the cheapest and most easily
        undone actions, while every call, send and deletion went through as intended. This is the behaviour
        the tiers are designed to produce: the interface can afford to be quick where a mistake costs one
        backspace, because it stays careful where a mistake cannot be taken back.

        **Implicit evidence is plentiful.** A gaze interface observes many more looks than selections. Stray
        glances and give-ups tell the learner how long the person’s glances last and how long they are willing
        to wait, at no cost to the person. The same abundance makes the labelling rules matter: an early
        version of our give-up rule counted every brief look on the way to a target as a give-up, which held the
        dwell at its floor. Rules that require a long look and a fresh choice of the same button removed this.

        **Personalised confirmation.** The two participants ended up with different confirmation strategies
        after only a few requests, and an explicit preference changed the router’s choice immediately. Letting
        the system learn which signal works, while the person keeps the final say, follows ability-based design
        and avoids fixing a signal that some people cannot produce reliably.

        **Target size over keystrokes on commodity sensors.** With phone-based gaze accurate to about one QWERTY
        key, fewer and larger targets beat one selection per letter. For commodity gaze sensing, layouts should be
        designed around the sensor’s error first, and the learned dwell then trims the time per selection.
        """))

    # 8 Limitations
    b.append(head1("Limitations and Future Work"))
    b.append(paras("""
        These results come from two able-bodied participants with no baseline condition, so they show that the
        learners behave as intended, not that adaptation beats a fixed dwell. The typing runs were recorded while
        the dwell was still learning, and grouped runs always came first; the typing test now uses a fixed dwell,
        and the order will be counterbalanced. With a 1500 ms start and a 20 selection warm-up, the learner needs
        about 70 selections to settle. The tired flag uses session length and time of day rather than a fatigue
        measure, and head pointing is built but not yet evaluated.

        We are extending the study to two more able-bodied participants and one participant with a motor
        impairment. Each will use the app twice with gaze pointing, once with the adaptive learners and once with
        a fixed baseline (1000 ms dwell, dwell alone on tier 2, the preferred signal on tier 3), in counterbalanced
        order, with practice, the four tasks and SUS in each session. We will compare accidents and give-ups per
        100 selections, task times and SUS with paired tests, and report the participant with a motor impairment
        as a case study.
        """))

    # 9 Ethics
    b.append(head1("Ethics"))
    b.append(paras("""
        Participation was voluntary; participants were told what the session involved and what was recorded,
        gave consent before starting, and could stop at any time. Breaks were offered between free use and the
        typing runs, and an experimenter was present throughout. Camera images are shown live only and never stored, speech is
        recognised on the phone and only the confirmation word is sent, and logs hold gaze and head coordinates
        and interaction events under participant codes, with no names, images or audio.
        """))

    # 10 Conclusion
    b.append(head1("Conclusion"))
    b.append(paras("""
        Communic-aid shows that one consumer phone can provide both the pointing and the confirmation signals for
        a hands-free messaging interface, and that the interface can learn, from ordinary use and without asking,
        how long to wait and which signal to ask for before acting. Treating dwell and confirmation as two
        settings of one question, scaled by the cost of an error, gives a simple way to make gaze interaction both
        safer and faster for each person.
        """))

    b.append(p("ReferenceHead", "REFERENCES"))
    b.extend(bib(i, text) for i, (_, text) in enumerate(REFS, 1))
    return "".join(b)


def set_properties(path: Path) -> None:
    """Set the title and author fields of the file; empty authors in the anonymous copy."""
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "docProps/core.xml":
                text = data.decode("utf-8")
                text = re.sub(r"<dc:creator>.*?</dc:creator>", f"<dc:creator>{'' if ANONYMOUS else 'Bisaria, Singh, Khaidem'}</dc:creator>", text, flags=re.S)
                text = re.sub(r"<dc:title>.*?</dc:title>", f"<dc:title>{TITLE}</dc:title>", text, flags=re.S)
                data = text.encode("utf-8")
            zout.writestr(item, data)
    tmp.replace(path)


if __name__ == "__main__":
    base.OUT = base.HERE / ("AH2027_v2" + ("_anonymous" if ANONYMOUS else "") + ("_gdocs" if base.GDOCS else "") + ".docx")
    base.build_body = build_body
    base.main(Path(sys.argv[1]))
    set_properties(base.OUT)
