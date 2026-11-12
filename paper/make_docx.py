"""Build paper/Report.docx from the ACM Word submission template.

    python paper/make_docx.py /path/to/acm_submission_template.docx

Keeps the template's styles, numbering, page setup and footers, and replaces its body with the
report. Inline marks in the text below: **bold**, *italic*, ~subscript~, {{yellow "to fill" mark}}.
"""

from __future__ import annotations

import re
import shutil
import struct
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
OUT = HERE / "Report.docx"
TEXT_WIDTH_IN = 6.0                  # the template's text block is 6.08 inches wide


# ---------- small builders ----------

def runs(text: str) -> str:
    """Turn the inline marks into Word runs."""
    out = []
    for part in re.split(r"(\*\*.+?\*\*|\*.+?\*|~.+?~|\{\{.+?\}\})", text):
        if not part:
            continue
        props = ""
        if part.startswith("**"):
            part, props = part[2:-2], "<w:b/>"
        elif part.startswith("{{"):
            part, props = f"[TO FILL: {part[2:-2]}]", "<w:b/><w:highlight w:val=\"yellow\"/>"
        elif part.startswith("*"):
            part, props = part[1:-1], "<w:i/>"
        elif part.startswith("~"):
            part, props = part[1:-1], "<w:i/><w:vertAlign w:val=\"subscript\"/>"
        rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return "".join(out)


def p(style: str, text: str = "", extra_ppr: str = "") -> str:
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{extra_ppr}</w:pPr>{runs(text)}</w:p>'


def head1(text: str) -> str:
    return p("Head1", text, '<w:tabs><w:tab w:val="clear" w:pos="360"/></w:tabs><w:ind w:left="432" w:hanging="432"/>')


def paras(text: str, first: bool = True) -> str:
    """Blank lines separate paragraphs. The first after a heading has no indent (PostHeadPara)."""
    blocks = [" ".join(b.split()) for b in text.strip().split("\n\n")]
    return "".join(p("PostHeadPara" if first and i == 0 else "Para", b) for i, b in enumerate(blocks))


IMAGES: list[tuple[str, Path]] = []


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


def figure(name: str, width_frac: float, number: int, caption: str, alt: str) -> str:
    path = FIG / name
    rid = f"rIdFig{len(IMAGES) + 1}"
    IMAGES.append((rid, path))
    w_px, h_px = png_size(path)
    cx = int(TEXT_WIDTH_IN * width_frac * 914400)
    cy = int(cx * h_px / w_px)
    n = len(IMAGES)
    drawing = (
        f'<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{100 + n}" name="Figure {number}" descr="{escape(alt, {chr(34): "&quot;"})}"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="{100 + n}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>')
    image = f'<w:p><w:pPr><w:pStyle w:val="Image"/><w:spacing w:before="120"/></w:pPr><w:r><w:rPr><w:noProof/></w:rPr>{drawing}</w:r></w:p>'
    return image + p("FigureCaption", f"Figure {number}: {caption}")


def table(number: int, caption: str, widths: list[int], rows: list[list[str]]) -> str:
    """A table in the template's style: rules above and below the header, and below the last row."""
    total = sum(widths)
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    out = [p("TableCaption", f"Table {number}: {caption}"),
           f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="{total}" w:type="dxa"/><w:jc w:val="center"/>'
           '<w:tblBorders><w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/><w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
           '<w:bottom w:val="none" w:sz="0" w:space="0" w:color="auto"/><w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
           '<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/><w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/></w:tblBorders>'
           '<w:tblCellMar><w:left w:w="60" w:type="dxa"/><w:right w:w="60" w:type="dxa"/></w:tblCellMar>'
           f'<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>']
    for r, row in enumerate(rows):
        header, last = r == 0, r == len(rows) - 1
        out.append("<w:tr>" + ("<w:trPr><w:tblHeader/></w:trPr>" if header else "<w:trPr><w:cantSplit/></w:trPr>"))
        for c, (cell, w) in enumerate(zip(row, widths)):
            borders = ""
            if header:
                borders = '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
            elif last:
                borders = '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
            text = f"**{cell}**" if header and cell else cell
            out.append(f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/><w:tcBorders>{borders}</w:tcBorders></w:tcPr>'
                       f'<w:p><w:pPr><w:pStyle w:val="TableCell"/>{"" if last else "<w:keepNext/>"}<w:ind w:firstLine="0"/><w:jc w:val="left"/></w:pPr>{runs(text)}</w:p></w:tc>')
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def formula(text: str) -> str:
    return f'<w:p><w:pPr><w:pStyle w:val="DisplayFormulaUnnum"/><w:jc w:val="center"/></w:pPr>{runs(text)}</w:p>'


# ---------- the report ----------

REFS = [
    "John Brooke. 1996. SUS: A “Quick and Dirty” Usability Scale. In *Usability Evaluation in Industry*. Taylor & Francis, 189-194.",
    "Y. Cha, D. Chun, and S. Park. 2026. iPhoneme: Brain-to-Text Communication for ALS Using ConformerXL Decoding. arXiv:2604.16441.",
    "Robert J. K. Jacob. 1990. What You Look at is What You Get: Eye Movement-Based Interaction Techniques. In *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems* (CHI ’90). ACM, 11-18. https://doi.org/10.1145/97243.97246",
    "Lihong Li, Wei Chu, John Langford, and Robert E. Schapire. 2010. A Contextual-Bandit Approach to Personalized News Article Recommendation. In *Proceedings of the 19th International Conference on World Wide Web* (WWW ’10). ACM, 661-670. https://doi.org/10.1145/1772690.1772758",
    "Päivi Majaranta, Ulla-Kaija Ahola, and Oleg Špakov. 2009. Fast Gaze Typing with an Adjustable Dwell Time. In *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems* (CHI ’09). ACM, 357-360. https://doi.org/10.1145/1518701.1518758",
    "Yogesh Kumar Meena and M. Salvi. 2025. Multimodal Appearance-Based Gaze-Controlled Virtual Keyboard with Synchronous-Asynchronous Interaction for Low-Resource Settings. https://doi.org/10.48550/arXiv.2508.16606",
    "Martez E. Mott, Shane Williams, Jacob O. Wobbrock, and Meredith Ringel Morris. 2017. Improving Dwell-Based Gaze Typing with Dynamic, Cascading Dwell Times. In *Proceedings of the 2017 CHI Conference on Human Factors in Computing Systems* (CHI ’17). ACM. https://doi.org/10.1145/3025453.3025517",
    "Omar Namnakani, Yasmeen Abdrabou, Jonathan Grizou, and Mohamed Khamis. 2025. GazeBlend: Exploring Paired Gaze-Based Input Techniques for Navigation and Selection Tasks on Mobile Devices. arXiv:2512.15491.",
    "Anish S. Narkar, Jan J. Michalak, Candace E. Peacock, and Brendan David-John. 2024. GazeIntent: Adapting Dwell-Time Selection in VR Interaction with Real-Time Intent Modeling. arXiv:2404.13829.",
    "R. William Soukoreff and I. Scott MacKenzie. 2003. Metrics for Text Entry Research: An Evaluation of MSD and KSPC, and a New Unified Error Metric. In *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems* (CHI ’03). ACM, 113-120. https://doi.org/10.1145/642611.642632",
    "William R. Thompson. 1933. On the Likelihood that One Unknown Probability Exceeds Another in View of the Evidence of Two Samples. *Biometrika* 25, 3/4 (1933), 285-294.",
    "Jacob O. Wobbrock, Shaun K. Kane, Krzysztof Z. Gajos, Susumu Harada, and Jon Froehlich. 2011. Ability-Based Design: Concept, Principles and Examples. *ACM Transactions on Accessible Computing* 3, 3 (2011). https://doi.org/10.1145/1952383.1952384",
    "Xiaoyi Zhang, Harish Kulkarni, and Meredith Ringel Morris. 2017. Smartphone-Based Gaze Gesture Communication for People with Motor Disabilities. In *Proceedings of the 2017 CHI Conference on Human Factors in Computing Systems* (CHI ’17). ACM, 2878-2889. https://doi.org/10.1145/3025453.3025790",
]
# Citation numbers, in the order of REFS (alphabetical, as ACM numbers them).
BROOKE, CHA, JACOB, LI, MAJARANTA, MEENA, MOTT, NAMNAKANI, NARKAR, SOUKOREFF, THOMPSON, WOBBROCK, ZHANG = range(1, 14)


def build_body() -> str:
    b = []
    b.append(p("Titledocument", "Communic-aid"))
    b.append(p("Subtitle", "Learning How Much Evidence to Ask For in Gaze-Based Messaging on a Commodity iPhone"))
    for name in ("Vandya Bisaria", "Mansie Singh", "Sinngam Khaidem"):
        b.append(p("Authors", name))
        b.append(p("Affiliation", "Indian Institute of Technology Gandhinagar, India"))
    b.append(p("Abstract", " ".join("""
        Gaze is often the most reliable input left to people with severe motor impairments, but gaze
        interfaces force one trade off on every action: a long dwell is slow, a short dwell selects
        things by mistake, and a fixed confirmation step is either too weak for a call or too tedious
        for a letter. Communic-aid is a working hands-free messaging prototype whose only sensor is an
        iPhone with a TrueDepth camera. The phone streams gaze, head pose, blinks, eyebrow raises and a
        spoken confirmation word to a laptop that runs a chat app with messages, calls and a gaze
        keyboard. Its central idea is that the interface learns how much evidence to ask for before it
        acts, per person, per context and per level of risk. Every action belongs to one of four risk
        tiers with an accident cost; a dwell learner sets the dwell from implicit feedback, and a
        contextual bandit chooses which confirmation signal, if any, to ask for on risky actions. In a
        controlled usability test with two able-bodied participants, the learner shortened the dwell
        from 1500 ms to about 1200 ms within one session, with two accidents in 146 selections, both
        on undoable letters and none on risky actions; the router adapted its choice of signal to each
        participant; and a grouped keyboard with large targets was 1.5 to 2.8 times faster than QWERTY.
        Three more participants, including one person with a motor impairment, are scheduled.
        """.split())))
    b.append('<w:p><w:pPr><w:pStyle w:val="CCSDescription"/></w:pPr><w:r><w:rPr><w:rStyle w:val="CCSHeadchar"/></w:rPr>'
             '<w:t xml:space="preserve">CCS CONCEPTS </w:t></w:r><w:r><w:t xml:space="preserve">• </w:t></w:r><w:r><w:rPr><w:b w:val="0"/></w:rPr>'
             '<w:t>Human-centered computing → Accessibility technologies • Human-centered computing → Interaction techniques</w:t></w:r></w:p>')
    b.append('<w:p><w:pPr><w:pStyle w:val="KeyWords"/></w:pPr><w:r><w:rPr><w:rStyle w:val="KeyWordHeadchar"/><w:b/></w:rPr>'
             '<w:t xml:space="preserve">Additional Keywords and Phrases: </w:t></w:r><w:r><w:t>gaze interaction, adaptive dwell time, '
             'multimodal confirmation, contextual bandit, motor impairment, high-fidelity prototype, usability evaluation</w:t></w:r></w:p>')
    b.append(p("ACMRefHead", "ACM Reference Format:"))
    b.append(p("ACMRef", "Vandya Bisaria, Mansie Singh, and Sinngam Khaidem. 2026. Communic-aid: Learning How "
                         "Much Evidence to Ask For in Gaze-Based Messaging on a Commodity iPhone. CS 435 Human-Computer "
                         "Interaction, Group Course Project, IIT Gandhinagar, November 2026."))

    # 1 System design and architecture
    b.append(head1("System Design and Architecture"))
    b.append(paras(f"""
        **Goal.** For many people with ALS, muscular dystrophy, cerebral palsy or spinal cord injury, the
        eyes remain controllable long after the hands. Gaze interfaces suffer from the Midas touch problem
        [{JACOB}]: the eyes are always looking at something, so the interface cannot tell “do this” from
        “I am reading”. The usual remedy is a *dwell* time: a button is selected only after the eyes have
        stayed on it long enough. Adaptive dwell methods tune one such threshold for all actions
        [{MAJARANTA}, {MOTT}, {NARKAR}], and multimodal methods add a fixed second signal [{CHA}, {NAMNAKANI}]. Our earlier
        reports identified three gaps: confirmation does not scale with the cost of an error, dwell
        adaptation rarely learns from implicit signals, and no system chooses the confirmation modality
        from experience. Communic-aid addresses all three with one question: *how much evidence should
        the interface ask for before it acts?*
        """))
    b.append(figure("architecture.png", 1.0, 1,
                    "Architecture. The iPhone only senses, the Python core makes every decision, and the browser "
                    "only draws. The dashed arrow is the learning loop: outcomes update the policy.",
                    "Block diagram: the iPhone sends face frames and a spoken confirmation over UDP to a Python core "
                    "with modules for input, signals, context, interaction, policy, outcomes, chat and persistence, "
                    "which talks to a browser view over a WebSocket."))
    b.append(paras("""
        **Architecture.** The system has three parts (Figure 1). (1) *iPhone app* (Swift, ARKit face
        tracking): sends at 60 Hz over UDP the gaze ray and eye position in camera space, the nose
        direction, and blink and eyebrow blendshapes. On-device speech recognition listens only for the
        word “go”. A live face preview helps the person position themselves. (2) *Core* (Python,
        asyncio): maps gaze to the screen with a nine point calibration (quadratic least squares with a
        small ridge term), smooths it with an exponential filter, holds it still during blinks, and
        corrects slow drift from the centres of buttons just selected. It detects signals with
        per-person thresholds set halfway between rest and peak in a signal check (blink held 500 ms,
        eyebrows raised 300 ms, the spoken word, or a switch key). It runs the dwell and confirmation
        logic, labels outcomes, updates the learners, and logs every event. (3) *View* (HTML, CSS and
        JavaScript over a WebSocket): draws the screens and animations and knows no rules. There is no
        external API: all logic runs locally, so face and gaze data never leave the two devices.

        **Risk tiers.** Every action belongs to a tier (Table 1) whose accident cost doubles with each
        step. Both learners use this cost.
        """, first=False))
    b.append(table(1, "Risk tiers. Tier 0 and 1 fire on the learned dwell; tier 2 and 3 add a confirmation step after a fixed 1000 ms dwell.",
                   [600, 3840, 700, 3500],
                   [["Tier", "Actions", "Cost", "Confirmation"],
                    ["0", "Open a chat, back, scroll, navigation", "1", "Learned dwell"],
                    ["1", "Letters, word suggestions, Space, Backspace, settings", "2", "Learned dwell"],
                    ["2", "Send, react, end a call", "4", "Router: dwell alone or a signal"],
                    ["3", "Call, delete, forward", "8", "Always a signal chosen by the router"]]))
    b.append(paras("""
        **Implicit outcomes.** The learners never ask the person for feedback. Instead, the core labels
        each look and each confirmation request from what the person does next (Table 2).
        """, first=False))
    b.append(table(2, "Implicit outcomes: how each event is labelled, and what it tells the learners.", [1500, 3900, 3240],
                   [["Outcome", "Rule", "What it tells the learner"],
                    ["Accident", "A selection undone within 5 s, or a letter deleted within 3 s", "The dwell was too short"],
                    ["Worked", "A selection that was not undone", "The dwell was long enough"],
                    ["Give-up", "A look filled at least half the dwell, then the same button was chosen afresh within 5 s", "The dwell was too long"],
                    ["Stray glance", "Any other look that did not fill", "Normal reading; how long glances last"],
                    ["Blocked", "A confirmation request timed out with no attempt", "The check stopped an unwanted action"]]))
    b.append(paras(f"""
        Statistics are kept per context group: rested or tired (over 20 minutes in, or evening) crossed
        with steady or shaky gaze (recent gaze spread over 1.5 times a steady baseline).

        **Dwell learner** (tiers 0 and 1). From counts of intended and unintended looks, stray glances
        and give-ups, it draws by Thompson sampling [{THOMPSON}] the probability *π* that a look is
        intended, a mean stray glance length *g* and a mean patience *p*, and scores each dwell *d* from
        800 to 2000 ms:
        """, first=False))
    b.append(formula("*V*(*d*) = *π* [ (1 − *G*(*d*)) (1 − *λd*) + *r*~give-up~ *G*(*d*) ] − (1 − *π*) *A*(*d*) *c*~tier~"))
    b.append(paras(f"""
        with *A*(*d*) = e^(−*d*/*g*) the chance a stray glance fires, *G*(*d*) = 1 − e^(−*d*/*p*) the
        chance the person gives up first, *λ* = 0.6 per second and *r*~give-up~ = −0.5. After each
        selection the dwell moves 5% towards the best *d*, by at most 10 ms when shortening and up to
        100 ms when lengthening. It starts at 1500 ms and holds for 20 selections per group. In words: a
        longer dwell stops more stray glances from firing, but makes the person wait and sometimes give
        up; the learner picks the dwell with the best balance, and a higher tier cost pushes it towards
        caution.

        **Modality router** (tiers 2 and 3). A contextual bandit [{LI}] keeps, per arm, tier and group,
        counts of worked, give-up, blocked and accident outcomes, samples their probabilities from a
        Dirichlet distribution and asks for the arm with the highest expected reward. A worked signal
        earns 1 minus its effort (which grows with the person’s time to produce it); a blocked accident
        earns a small reward; an accident costs the tier cost. The preferred signal starts with a bonus,
        and a group borrows pooled counts until it has 20 tries. In short, the router learns which
        confirmation works best for each person and context, at the lowest effort.
        """))

    # 2 Compromises
    b.append(head1("Compromises in Prototyping"))
    b.append(paras("""
        We built the prototype wide enough to show every screen of a messaging app, and deep along the
        one path that carries our research question: from the camera to the learners (Table 3).
        """))
    b.append(table(3, "Horizontal and vertical scope of the prototype.", [1240, 3700, 3700],
                   [["", "Horizontal (breadth)", "Vertical (depth)"],
                    ["Scope", "Every screen: onboarding, signal check, calibration, chat list, thread, compose, call, message actions, settings, typing test",
                     "The full path from sensing to learning, working end to end with real users"],
                    ["Real", "Navigation, layout, feedback, undo, tier colours, both keyboards, word suggestions and quick replies",
                     "Gaze and head pointing, signal detection, dwell and confirmation, outcome labelling, both learners, per-person saving, logging and analysis"],
                    ["Simulated", "Contacts, chats and replies come from a local file; replies arrive after 7 s; calls connect after 3 s with no audio",
                     "Nothing on this path is simulated"]]))
    b.append(paras("""
        **Other compromises.** (1) The phone is a sensor for a laptop screen rather than a standalone app,
        which keeps targets large and lets us log everything, but adds a second device. (2) An iPhone with
        Face ID is required; apps are signed with a free developer account that expires every 7 days.
        (3) Speech recognises one word, “go”, rather than dictation, which our interviewee with slurred
        speech found unreliable. (4) Word suggestions come from a fixed word list, not a language model.
        (5) Head pointing is built but not yet evaluated. (6) The tired flag uses a simple rule (session
        length or evening) rather than a fatigue measure.
        """))

    # 3 Conceptual design
    b.append(head1("Conceptual Design"))
    b.append(paras(f"""
        **Metaphor.** Communic-aid borrows the *messaging app* people already know: chats, threads, a call
        button, a draft box and Send, so no new model of communication must be learned. Selection follows
        a *press and hold* metaphor: looking at a button presses it, and the button fills like a progress
        bar until it fires, so a look can always be abandoned before it counts. Risky buttons add a
        *safety catch*, like the second step of a slide to unlock: after the fill, the button shows the
        signal it needs (an eye, an eyebrow, “go”), and nothing happens without it.

        **Conceptual model.** The objects are chats, messages, contacts and a draft; the actions are open,
        type, send, react, call, delete, forward and undo. Each action carries a tier, and the tier, not
        the screen, decides how much evidence it needs. The user controls what to do, which signals are
        on and which comes first; the system controls how long to wait and when to ask for a signal, and
        it adjusts both from how the person uses it. Every action can be undone for 5 seconds, and losing
        the face never fires anything.

        **Design principles.** From our interviews with three people with motor impairments and the
        literature: (1) calm and low effort, nothing rushes or startles; (2) every visual element gives
        feedback or prevents a mistake; (3) the cost of an error decides the check; (4) learn from
        implicit behaviour, never from ratings; (5) reading is safe: text is never a target, only buttons
        are.

        **Design space.** Table 4 lists the dimensions we explored and our choices. The choices favour
        mainstream hardware [{ZHANG}, {MEENA}] and per-person adaptation, in the spirit of ability-based
        design [{WOBBROCK}].
        """))
    b.append(table(4, "Design space. Options we considered for each dimension, and the one we chose.", [1500, 3570, 3570],
                   [["Dimension", "Options considered", "Chosen"],
                    ["Sensor", "Eye tracker, webcam, iPhone TrueDepth", "iPhone TrueDepth: cheap, mainstream, depth based"],
                    ["Pointing", "Gaze, head, gaze and head", "Gaze, with head pointing as an option"],
                    ["Selection", "Dwell, blink, smooth pursuit, gaze gestures", "Dwell with a learned time"],
                    ["Confirmation", "None, fixed second signal, user chosen, learned", "Learned per tier and context"],
                    ["Signals", "Blink, eyebrows, voice, switch, EMG, BCI", "Blink and hold, eyebrows, “go”, switch"],
                    ["Adaptation", "Explicit ratings, implicit outcomes", "Implicit outcomes"],
                    ["Text entry", "QWERTY, grouped letters, dwell-free, AI text", "Grouped (default) and QWERTY, with suggestions and quick replies"],
                    ["Feedback", "Visual, sound, colour coding", "All three"]]))

    # 4 Prototype
    b.append(head1("Prototype Description and Functionalities"))
    b.append(paras("""
        Figure 2 shows the main screens. The core interaction flow is: look at a button, watch it fill,
        and for a risky button give the signal it shows.
        """))
    b.append(figure("screens.png", 0.92, 2,
                    "Screens of the working prototype. In (f) the Delete button has filled and now shows the closed "
                    "eye: it waits for blink and hold before it deletes.",
                    "Six screenshots of a dark interface with large buttons: chat list, thread, compose with letter "
                    "groups, the second letter step, message actions, and Delete filled red with a closed eye icon."))
    b.append(paras("""
        **Navigation.** Chats and Settings sit in a fixed side bar; Back, scroll buttons and the undo strip
        are in the same places on every screen. A chat opens a thread; More on a message opens its actions
        (React, Forward, Delete); Call opens a call screen with End call.

        **Text entry.** The grouped keyboard has eight letter groups (abc to wxyz): a group, then a letter
        (Figure 2c, d). QWERTY is one selection per letter. Both offer word suggestions and five quick
        replies.

        **Feedback and transitions.** A pink dot shows where the system thinks the person is looking.
        Buttons fill as they are looked at and glow when they fire; tier 2 buttons have an amber outline
        and tier 3 a red one. A confirmation request shows the signal’s icon on the button and waits up to
        4 s; a wrong signal makes the button shake and plays a soft error tone, and a confirmed one plays a
        tick. After any action a teal undo strip appears for 5 s. Plain language banners appear when
        tracking fails (“I can’t see your eyes. Look at the screen.”, “Move a little closer”), and only
        after the problem has lasted a second, so they never flicker.

        **Setup and settings.** First use asks three onboarding questions, then runs the signal check and
        calibration (redone automatically if the error exceeds 100 px). Settings turn signals on or off,
        choose the one to try first, switch sounds and keyboard, and rerun calibration or the signal check.
        Three switch presses always escape to safety.

        **Study tools.** A typing test mode shows a passage and measures words per minute for two minutes
        from the first letter. A terminal log shows every learner decision live. Scripts produce
        per-person heatmaps, dwell plots and summary tables. The core has 79 automated tests.
        """, first=False))

    # 5 Evaluation
    b.append(head1("User Evaluation and Results"))
    b.append(paras(f"""
        **Method.** We ran a task-based usability test in a controlled setting (a quiet room, laptop on a
        desk, phone mounted below the screen at 40 to 60 cm, head free to move), with an experimenter
        present. Data came from three sources: the system’s event log (every look, selection, outcome and
        learner update), a two minute typing test, and the System Usability Scale [{BROOKE}] with open
        feedback after the session.

        **Participants.** Two able-bodied adults (P1, P2) have completed the test with gaze pointing in the
        adaptive condition. Two more able-bodied participants and one participant with a motor impairment
        are scheduled.

        **Procedure.** Signal check and calibration; free use of the app; four tasks (navigate between
        chats and settings and change the preferred signal; compose and send a message of at least ten
        letters; make and end a call; delete a message); then the typing test, three runs with each
        keyboard, grouped first, a new 248 character passage each run, no word suggestions. Free use lasted
        9 minutes for P1 and 24 for P2. We report words per minute ((*n* − 1)/*t* × 60/5 for *n*
        characters in *t* seconds), accuracy from the edit distance to the passage, and keystrokes per
        character [{SOUKOREFF}].
        """))
    b.append(table(5, "Free use session, from the event log. Selections exclude undo and redo.", [4440, 2100, 2100],
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
        undone (Table 5). No tier 2 or 3 action fired by mistake. 16 of 18 confirmation requests succeeded.
        The router adapted within each session: when P1 gave up on raised eyebrows to confirm Send, the next
        Send asked for blink and hold, which worked, as did the call and the deletion that followed. P2
        began with blink and hold; after three successful confirmations the router accepted dwell alone on
        tier 2 (four times, all worked), and after P2 made “go” the preferred signal, P2 confirmed it five
        times out of five.

        **Dwell learning.** Stray glances outnumbered selections three to six times: a gaze interface
        produces much implicit evidence even when nothing is selected. After its warm-up the learner
        shortened both tiers steadily (Figure 3); tier 0 fell from 1500 to about 1220 ms for both
        participants. Tier 1 stayed longer, as expected from its higher cost. A new context group (P1,
        tired with shaky gaze) started from 1500 ms and was learned separately.
        """, first=False))
    b.append(figure("dwell_p1.png", 0.78, 3,
                    "P1’s dwell over all sessions, one panel per context group, one line per tier. The first session "
                    "is free use, then three grouped and three QWERTY typing runs. Shading marks the warm-up; marks at "
                    "the bottom are selections (light) and accidents (dark).",
                    "Two step plots of dwell against selection count, each falling from 1500 ms after a warm-up."))
    b.append(paras("""
        **Typing.** The grouped keyboard was 1.5 (P1) and 2.8 (P2) times faster than QWERTY (Table 6),
        despite almost two selections per letter, and not because of the dwell, which was slightly shorter
        in the QWERTY runs. Target size explains it: a letter group was 316 × 113 px and a QWERTY key
        113 × 67 px, while the calibration error was 69 to 80 px, about one QWERTY key.
        """, first=False))
    b.append(table(6, "Typing test, mean of three two minute runs per keyboard. The dwell was still learning during this test, so the mean tier 1 dwell in use is shown.",
                   [800, 1400, 1300, 1500, 2140, 1500],
                   [["", "Keyboard", "WPM", "Accuracy", "Keystrokes per char.", "Mean dwell"],
                    ["P1", "Grouped", "2.23", "100%", "1.84", "1261 ms"],
                    ["", "QWERTY", "1.50", "91.7%", "1.06", "1214 ms"],
                    ["P2", "Grouped", "1.60", "100%", "1.86", "1327 ms"],
                    ["", "QWERTY", "0.57", "100%", "1.11", "1259 ms"]]))
    b.append(paras("**Usability (SUS).** Table 7 gives the System Usability Scale scores (0 to 100; about 68 is average).", first=False))
    b.append(table(7, "System Usability Scale.", [2640, 3000, 3000],
                   [["", "P1", "P2"],
                    ["SUS score", "{{P1 SUS}}", "{{P2 SUS}}"]]))
    b.append(paras("""
        **User feedback.** {{what P1 and P2 said: what worked, what was hard, what they would change}}

        **Limitations.** Two able-bodied participants and no fixed baseline yet, so the results show that
        the learners behave as intended, not that adaptation beats a fixed dwell. The typing runs were
        recorded while the dwell was learning and grouped always came first; the typing test now uses a
        fixed dwell, and the order will be counterbalanced. With a 1500 ms start and a 20 selection warm-up
        the learner needs about 70 selections to settle. The remaining three participants will use the app
        twice, adaptive and fixed (1000 ms dwell, dwell alone on tier 2, the preferred signal on tier 3), in
        counterbalanced order, with SUS after each.
        """, first=False))

    # 6 Ethics
    b.append(head1("Ethics and Risk Assessment"))
    b.append(paras("Table 8 lists the risks we identified and our mitigations. An experimenter supervised every session."))
    b.append(table(8, "Risks to participants and how we reduce them.", [2340, 6300],
                   [["Risk", "Mitigation"],
                    ["Eye strain and fatigue", "Breaks offered between parts; the person can pause or stop at any time; the dwell lengthens after errors instead of rushing the person"],
                    ["Neck strain or discomfort", "Head free to move; phone placed at a comfortable distance; banners ask the person to move only when tracking fails"],
                    ["Frustration from errors", "Undo on every action for 5 s; risky actions need a second signal; a hint after 30 s of being stuck; no time pressure except the typing test"],
                    ["Privacy of face and voice", "Camera images are shown live only and never stored; speech is recognised on the phone and only the word “go” is sent; nothing goes to a cloud service"],
                    ["Identification from data", "Data is saved under a participant code (P1, P2); names are kept apart from the data; the shared evaluation data uses codes only"]]))
    b.append(paras("""
        The logs hold gaze coordinates, head position and angles, and interaction events; they hold no
        images, audio or names. The onboarding screen offers an age range and a condition category;
        participants could pick any option, these answers served as selection practice, and they were not
        analysed.

        **Statement.** Participation is voluntary. Each participant is told what the session involves and
        what is recorded, gives consent before starting, and may stop at any time without giving a reason.
        No sensitive personal data (names, contact details, images, audio or health records) is collected;
        the data is stored on the team’s computer under participant codes and used only for this course
        project and its write-up.
        """, first=False))

    # 7 Conclusion
    b.append(head1("Conclusion"))
    b.append(paras("""
        Communic-aid is a working high-fidelity prototype in which one consumer phone provides both pointing
        and confirmation for hands-free messaging, and the interface learns from ordinary use, without
        asking, how long to wait and which signal to ask for before acting. Early tests show rare, cheap,
        undoable accidents, no accidents on risky actions, a dwell that shortens within one session, and a
        router that adapts to each person. The remaining sessions will compare adaptive against fixed
        settings and include a participant with a motor impairment.
        """))

    b.append(p("ReferenceHead", "REFERENCES"))
    b.extend(p("Bibentry", r) for r in REFS)
    return "".join(b)


def main(template: Path) -> None:
    work = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(template) as z:
        z.extractall(work)
    doc = (work / "word/document.xml").read_text(encoding="utf-8")
    start = doc.index("<w:body>") + len("<w:body>")
    sect = doc.rindex("<w:sectPr")
    doc = doc[:start] + build_body() + doc[sect:]
    (work / "word/document.xml").write_text(doc, encoding="utf-8")

    # Drop the template's sample pictures and their links; add ours.
    rels_path = work / "word/_rels/document.xml.rels"
    rels = rels_path.read_text(encoding="utf-8")
    rels = re.sub(r'<Relationship [^>]*Type="[^"]*/image"[^>]*/>', "", rels)
    for f in (work / "word/media").glob("*"):
        f.unlink()
    new = ""
    for i, (rid, path) in enumerate(IMAGES, 1):
        target = f"media/figure{i}.png"
        shutil.copy(path, work / "word" / target)
        new += f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{target}"/>'
    rels_path.write_text(rels.replace("</Relationships>", new + "</Relationships>"), encoding="utf-8")

    core = work / "docProps/core.xml"
    c = core.read_text(encoding="utf-8")
    c = re.sub(r"<dc:title>.*?</dc:title>", "<dc:title>Communic-aid</dc:title>", c, flags=re.S)
    c = re.sub(r"<dc:creator>.*?</dc:creator>", "<dc:creator>Bisaria, Singh, Khaidem</dc:creator>", c, flags=re.S)
    c = re.sub(r"<cp:lastModifiedBy>.*?</cp:lastModifiedBy>", "<cp:lastModifiedBy></cp:lastModifiedBy>", c, flags=re.S)
    core.write_text(c, encoding="utf-8")

    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(work.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(work).as_posix())
    shutil.rmtree(work)
    print(f"saved {OUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
