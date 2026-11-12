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
    "William R. Thompson. 1933. On the Likelihood that One Unknown Probability Exceeds Another in View of the Evidence of Two Samples. *Biometrika* 25, 3/4 (1933), 285-294.",
    "Jacob O. Wobbrock, Shaun K. Kane, Krzysztof Z. Gajos, Susumu Harada, and Jon Froehlich. 2011. Ability-Based Design: Concept, Principles and Examples. *ACM Transactions on Accessible Computing* 3, 3 (2011). https://doi.org/10.1145/1952383.1952384",
    "Xiaoyi Zhang, Harish Kulkarni, and Meredith Ringel Morris. 2017. Smartphone-Based Gaze Gesture Communication for People with Motor Disabilities. In *Proceedings of the 2017 CHI Conference on Human Factors in Computing Systems* (CHI ’17). ACM, 2878-2889. https://doi.org/10.1145/3025453.3025790",
]
# Citation numbers, in the order of REFS (alphabetical, as ACM numbers them).
BROOKE, CHA, JACOB, LI, MAJARANTA, MEENA, MOTT, NAMNAKANI, THOMPSON, WOBBROCK, ZHANG = range(1, 12)


def build_body() -> str:
    b = []
    b.append(p("Titledocument", "Communic-aid"))
    b.append(p("Subtitle", "A Gaze-Controlled Messaging App That Learns How Careful to Be"))
    for name in ("Vandya Bisaria", "Mansie Singh", "Sinngam Khaidem"):
        b.append(p("Authors", name))
        b.append(p("Affiliation", "Indian Institute of Technology Gandhinagar, India"))
    b.append(p("Abstract", " ".join("""
        People with severe motor impairments can often still move their eyes. Communic-aid lets them
        message and call using only their eyes and face. An iPhone with a Face ID camera tracks where
        the person looks, and a laptop shows a simple chat app. To press a button, the person looks at
        it until it fills. Risky actions, like calling or deleting, also need a second signal: a long
        blink, raised eyebrows, saying “go”, or a switch. The app learns from how each person uses it.
        It shortens the waiting time when the person is accurate, and it learns which second signal works
        best for them. We tested the working prototype with two participants. There were only two mistaken
        presses in 146, both on letters and both undone, and none on risky actions. The waiting time
        dropped from 1.5 to about 1.2 seconds within one session, and a keyboard with large letter groups
        was faster than a normal QWERTY keyboard. Three more participants, including one person with a
        motor impairment, are scheduled.
        """.split())))
    b.append('<w:p><w:pPr><w:pStyle w:val="CCSDescription"/></w:pPr><w:r><w:rPr><w:rStyle w:val="CCSHeadchar"/></w:rPr>'
             '<w:t xml:space="preserve">CCS CONCEPTS </w:t></w:r><w:r><w:t xml:space="preserve">• </w:t></w:r><w:r><w:rPr><w:b w:val="0"/></w:rPr>'
             '<w:t>Human-centered computing → Accessibility technologies • Human-centered computing → Interaction techniques</w:t></w:r></w:p>')
    b.append('<w:p><w:pPr><w:pStyle w:val="KeyWords"/></w:pPr><w:r><w:rPr><w:rStyle w:val="KeyWordHeadchar"/><w:b/></w:rPr>'
             '<w:t xml:space="preserve">Additional Keywords and Phrases: </w:t></w:r><w:r><w:t>eye gaze, accessibility, '
             'motor impairment, adaptive interface, messaging, high-fidelity prototype</w:t></w:r></w:p>')
    b.append(p("ACMRefHead", "ACM Reference Format:"))
    b.append(p("ACMRef", "Vandya Bisaria, Mansie Singh, and Sinngam Khaidem. 2026. Communic-aid: A "
                         "Gaze-Controlled Messaging App That Learns How Careful to Be. CS 435 Human-Computer Interaction, "
                         "Group Course Project, IIT Gandhinagar, November 2026."))

    # 1 System design and architecture
    b.append(head1("System Design and Architecture"))
    b.append(paras(f"""
        **The problem.** When eyes are used as a mouse, the computer cannot tell whether the person is
        reading a button or wants to press it [{JACOB}]. The usual fix is a waiting time, called *dwell*:
        a button is pressed only after the person has looked at it for, say, one second. A long dwell is
        safe but slow. A short dwell is fast but presses things by mistake. Most systems pick one dwell
        for everything [{MAJARANTA}, {MOTT}], or always ask for the same extra signal [{CHA}, {NAMNAKANI}].

        **Our idea.** A mistaken letter is easy to fix, but a mistaken call is not. So Communic-aid asks
        for more proof when a mistake would cost more, and it learns from each person how much proof they
        need.
        """))
    b.append(figure("architecture.png", 1.0, 1,
                    "How the parts connect. The iPhone only senses, the laptop program makes every decision, "
                    "and the browser only draws the screen.",
                    "Block diagram: the iPhone sends face data over Wi-Fi to a Python program, which talks to a "
                    "browser window."))
    b.append(paras("""
        **Three parts** (Figure 1). (1) The **iPhone app** uses the Face ID camera to measure where the
        eyes point, how the head is turned, and whether the person blinks or raises their eyebrows. It also
        listens for the word “go”. It sends this 60 times a second over Wi-Fi. (2) The **laptop program**
        (Python) turns eye direction into a point on the screen, after a short calibration where the person
        looks at nine dots. It decides when a button is pressed, checks the second signals, and learns. (3)
        The **screen** is a web page that only draws what the program tells it. No data goes to the
        internet.

        **Risk levels.** Every button has a risk level, or *tier* (Table 1). The higher the tier, the more
        a mistake costs, and the more care the app takes.
        """, first=False))
    b.append(table(1, "The four risk levels.", [700, 3700, 900, 3340],
                   [["Tier", "Buttons", "Cost of a mistake", "What the person does"],
                    ["0", "Open a chat, go back, scroll", "1", "Look until it fills"],
                    ["1", "Letters, word suggestions, settings", "2", "Look until it fills"],
                    ["2", "Send, react, end a call", "4", "Look, then maybe a second signal"],
                    ["3", "Call, delete, forward", "8", "Look, then always a second signal"]]))
    b.append(paras("""
        **How the app knows what went wrong.** The app never asks the person to rate anything. It watches
        what they do next (Table 2).
        """, first=False))
    b.append(table(2, "What the app learns from.", [2400, 6240],
                   [["What happened", "What it means"],
                    ["Pressed, then undone within 5 s", "A mistake: the dwell was too short"],
                    ["Looked long, left, then came back to the same button", "The person gave up waiting: the dwell was too long"],
                    ["A short look that pressed nothing", "Just a glance: normal reading"],
                    ["Asked for a signal, and it came", "That signal works for this person"],
                    ["Asked for a signal, and nothing came", "The check stopped an action the person did not want"]]))
    b.append(paras(f"""
        **Two learners.** The *dwell learner* sets the waiting time for tiers 0 and 1. Mistakes make it
        longer quickly; success makes it shorter slowly, so it stays safe. The *signal chooser* decides,
        for tiers 2 and 3, which second signal to ask for. It keeps a score for each signal and picks the
        one most likely to work with the least effort. Both use a standard method that tries out options
        while learning, so a signal that failed once is not ruled out forever [{THOMPSON}, {LI}]. Each
        learner keeps separate records for whether the person seems tired (more than 20 minutes in, or in
        the evening) and whether their gaze is steady or shaky.
        """, first=False))

    # 2 Compromises
    b.append(head1("Compromises in Prototyping"))
    b.append(paras("""
        We made the prototype *wide* enough to show every screen of a messaging app, and *deep* along
        the one path that matters most for our idea: from the camera to the learning (Table 3).
        """))
    b.append(table(3, "What is real and what is simulated.", [1240, 3700, 3700],
                   [["", "Horizontal (all screens)", "Vertical (the main path)"],
                    ["Covers", "Setup, calibration, chat list, chat, typing, call, message actions, settings, typing test",
                     "Eye tracking, signals, pressing buttons, learning, saving data"],
                    ["Real", "Navigation, feedback, undo, both keyboards, word suggestions",
                     "Everything works end to end with real users"],
                    ["Simulated", "Contacts and replies come from a file; calls connect but have no sound",
                     "Nothing"]]))
    b.append(paras("""
        **Other compromises.** The phone works with a laptop instead of on its own, so the buttons can be
        large. It needs an iPhone with Face ID. Speech only recognises one word, “go”. Word suggestions come
        from a fixed word list, not AI. Pointing with the head is built but not yet tested.
        """))

    # 3 Conceptual design
    b.append(head1("Conceptual Design"))
    b.append(paras(f"""
        **Metaphor.** The app looks like a familiar **messaging app**: chats, messages, a call button and
        Send. Pressing works like **press and hold**: looking at a button presses it, and it fills like a
        progress bar, so looking away cancels. Risky buttons have a **safety catch**, like “slide to
        unlock”: after the button fills, it shows the signal it needs, and nothing happens without it.

        **Design principles.** (1) Calm and low effort: nothing rushes the person. (2) Every visual element
        gives feedback or prevents a mistake. (3) The cost of a mistake decides how careful to be. (4) Learn
        from behaviour, never ask for ratings. (5) Reading is safe: only buttons react to the eyes, never
        text.

        **Design space.** Table 4 shows the options we considered and what we chose. We favoured
        everyday hardware [{ZHANG}, {MEENA}] and fitting the app to each person [{WOBBROCK}].
        """))
    b.append(table(4, "Design choices.", [1500, 3570, 3570],
                   [["Choice", "Options", "Chosen"],
                    ["Sensor", "Eye tracker, webcam, iPhone", "iPhone: cheap and common"],
                    ["Pointing", "Eyes, head", "Eyes (head as an option)"],
                    ["Pressing", "Look and wait, blink, eye gestures", "Look and wait, with a learned time"],
                    ["Second signal", "None, always the same, learned", "Learned, only on risky buttons"],
                    ["Signals", "Blink, eyebrows, voice, switch", "All four, chosen per person"],
                    ["Keyboard", "QWERTY, letter groups", "Letter groups (default) and QWERTY"],
                    ["Feedback", "Visual, sound, colour", "All three"]]))

    # 4 Prototype
    b.append(head1("Prototype Description and Functionalities"))
    b.append(paras("""
        Figure 2 shows the main screens. The basic flow is: look at a button, watch it fill, and for a
        risky button give the signal it shows.
        """))
    b.append(figure("screens.png", 0.92, 2,
                    "Screens of the working prototype. In (f) the Delete button has filled and shows a closed eye: "
                    "it waits for a long blink before deleting.",
                    "Six screenshots: chat list, chat, keyboard with letter groups, letter choice, message "
                    "actions, and Delete waiting for a blink."))
    b.append(paras("""
        **Navigation.** Chats and Settings are always on the left. Back and Undo are always in the same
        place. A chat shows its messages; “More” on a message offers React, Forward and Delete.

        **Typing.** The default keyboard has eight large letter groups (abc, def and so on). The person
        picks a group, then a letter (Figure 2c, d). A QWERTY keyboard is also available. Both show word
        suggestions and quick replies such as “I am fine”.

        **Feedback.** A pink dot shows where the app thinks the person is looking. Buttons fill while looked
        at. Risky buttons have amber (tier 2) or red (tier 3) borders. A soft tick confirms a signal, and a
        shake shows a wrong one. After every action, an Undo bar appears for 5 seconds. If the camera loses
        the face, a message says what to do, for example “Move a little closer”.

        **Setup and settings.** First use has a few questions, a check of each signal, and calibration.
        Settings let the person turn signals on or off, choose which comes first, and switch keyboards.
        """, first=False))

    # 5 Evaluation
    b.append(head1("User Evaluation and Results"))
    b.append(paras(f"""
        **Method.** A task-based usability test in a controlled setting: a quiet room, the phone below the
        laptop screen, an experimenter present. We used three sources of data: the app’s own log of every
        look and press, a two-minute typing test, and the System Usability Scale (SUS) [{BROOKE}] with open
        feedback.

        **Participants.** Two able-bodied adults (P1 and P2) have done the test. Two more able-bodied
        participants and one person with a motor impairment are scheduled.

        **Tasks.** After setup, each person used the app freely and did four tasks: (1) go to Settings and
        change the preferred signal, (2) type and send a message of at least ten letters, (3) make a call
        and end it, (4) delete a message. Then they did the typing test three times with each keyboard.
        """))
    b.append(table(5, "Results from the app’s log.", [4440, 2100, 2100],
                   [["Measure", "P1", "P2"],
                    ["Time using the app", "9 min", "24 min"],
                    ["Buttons pressed", "51", "95"],
                    ["Mistaken presses", "2 (letters, both undone)", "0"],
                    ["Risky actions (tier 2 and 3)", "4", "12"],
                    ["Mistakes on risky actions", "0", "0"],
                    ["Second signals asked / given", "5 / 4", "9 / 8"],
                    ["Dwell at the end (navigation / typing)", "1.22 / 1.33 s", "1.22 / 1.43 s"]]))
    b.append(paras("""
        **Finding 1: few mistakes, none on risky actions.** Out of 146 presses, only two were mistakes, both
        letters, and both were undone. No call, send or delete happened by mistake (Table 5).

        **Finding 2: the waiting time got shorter.** Every dwell started at 1.5 seconds. After 20 presses
        the learner began to shorten it, and by the end it was about 1.2 seconds for navigation for both
        participants (Figure 3). Typing buttons stayed a little slower, because their mistakes cost more.
        """, first=False))
    b.append(figure("dwell_p1.png", 0.78, 3,
                    "How P1’s dwell changed over all sessions. Each panel is one context (here, tired with steady "
                    "or shaky gaze); the two lines are navigation and typing buttons. The grey area is the first 20 "
                    "presses, when the dwell stays at 1.5 s.",
                    "Two step plots of dwell against presses, both falling from 1500 ms after 20 presses."))
    b.append(paras("""
        **Finding 3: the app learned which signal suits each person.** When P1 gave up on raising the
        eyebrows to send a message, the app asked for a long blink next time, and it worked. P2 confirmed
        risky actions reliably, so after three successes the app began to accept a look alone for some
        tier 2 actions, such as Send. Calls and deletions always still needed a signal.

        **Finding 4: big letter groups beat QWERTY.** The grouped keyboard was 1.5 times (P1) and 2.8 times
        (P2) faster, even though each letter needs two presses (Table 6). The reason is size: eye tracking
        is accurate to about 70 to 80 pixels, which is about the height of a QWERTY key, while a letter
        group is much bigger.
        """, first=False))
    b.append(table(6, "Typing test: average of three two-minute runs per keyboard.", [1500, 2380, 2380, 2380],
                   [["", "Keyboard", "Words per minute", "Accuracy"],
                    ["P1", "Letter groups", "2.2", "100%"],
                    ["", "QWERTY", "1.5", "92%"],
                    ["P2", "Letter groups", "1.6", "100%"],
                    ["", "QWERTY", "0.6", "100%"]]))
    b.append(paras("**Usability.** Table 7 gives the SUS scores (0 to 100; about 68 is average).", first=False))
    b.append(table(7, "System Usability Scale scores.", [2640, 3000, 3000],
                   [["", "P1", "P2"],
                    ["SUS score", "{{P1 SUS}}", "{{P2 SUS}}"]]))
    b.append(paras("""
        **User feedback.** {{what P1 and P2 said: what worked, what was hard, what they would change}}

        **Limitations.** So far there are only two participants, both without impairments, and no
        comparison with a fixed dwell yet. The typing test was run while the dwell was still learning; it
        now uses a fixed dwell. The remaining participants will use the app twice, once learning and once
        fixed, in a balanced order.
        """, first=False))

    # 6 Ethics
    b.append(head1("Ethics and Risk Assessment"))
    b.append(paras("Table 8 lists the possible risks and how we reduce them. An experimenter supervised every session."))
    b.append(table(8, "Risks and how we reduce them.", [2340, 6300],
                   [["Risk", "What we do"],
                    ["Tired eyes", "Sessions under 30 minutes, breaks offered, the person can stop at any time"],
                    ["Neck or body discomfort", "The head is free to move and the phone is placed at a comfortable distance"],
                    ["Frustration", "Undo on every action, a hint after 30 seconds of being stuck, no time pressure except in the typing test"],
                    ["Privacy", "Camera images are shown live only and never saved; speech is recognised on the phone; nothing goes online"],
                    ["Being identified", "Data is saved under a code (P1, P2), never under a name"]]))
    b.append(paras("""
        The logs hold only eye and head positions and button presses: no images, sound or names. The setup
        questions (age range and condition) were used only as practice for pressing buttons and were not
        analysed.

        **Statement.** Taking part is voluntary. Each participant is told what the session involves and
        what is recorded, agrees before starting, and can stop at any time without giving a reason. No
        sensitive personal data (names, contact details, photos, audio or health records) is collected. The
        data is kept on the team’s computer under codes and used only for this course project.
        """, first=False))

    # 7 Conclusion
    b.append(head1("Conclusion"))
    b.append(paras("""
        Communic-aid shows that an ordinary iPhone can let a person message and call using only their eyes
        and face. Instead of one fixed rule, the app takes more care on risky actions and learns, from how
        each person uses it, how long to wait and which signal to ask for. Early tests show few mistakes,
        none on risky actions, and a waiting time that shortens as the app learns. Next, we will test it
        with more people, including a person with a motor impairment.
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
