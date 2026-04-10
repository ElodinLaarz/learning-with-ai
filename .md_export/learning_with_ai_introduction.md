# Learning with AI

## IUTT and the abc conjecture

I wanted to learn how [Inter-universal Teichmüller theory (IUTT)](https://en.wikipedia.org/wiki/Inter-universal_Teichm%C3%BCller_theory) connects to the **abc conjecture**.

The core papers are long — not “long chapter” long, but “small book series” long:

- [I — Construction of Hodge Theaters](https://www.kurims.kyoto-u.ac.jp/~motizuki/Inter-universal%20Teichmuller%20Theory%20I.pdf) (186 pp.)
- [II](https://www.kurims.kyoto-u.ac.jp/~motizuki/Inter-universal%20Teichmuller%20Theory%20II.pdf) (174 pp.)
- [III](https://www.kurims.kyoto-u.ac.jp/~motizuki/Inter-universal%20Teichmuller%20Theory%20III.pdf) (199 pp.)
- [IV](https://web.archive.org/web/20161228071338/http://www.kurims.kyoto-u.ac.jp/~motizuki/Inter-universal%20Teichmuller%20Theory%20IV.pdf) (87 pp.; archived PDF)

That is **646 pages** of very dense mathematics — enough that even specialists treating it as a serious project reportedly needed on the order of **six years** to digest.

---

### From NotebookLM *(IUTT notebook)*

**Question:** How long was it between the first IUTT paper and when Peter Scholze wrote that abc is still a conjecture?

    **Answer (summary):** Mochizuki’s *Inter-universal Teichmüller Theory I* appeared as a preprint in **2012-08** (August 2012). Scholze and Jakob Stix circulated *Why abc is still a conjecture* in **2018** — Mochizuki cites a **2018-05** version, while the manuscript itself is dated **2018-07-16**. Depending on which 2018 date you use, the interval is about **5 years 9 months to ~6 years** between the first IUTT preprint and their case that the abc conjecture remains open.

## On the structure of this Notebook

I suppose I should explain how I am writing this, and what it is meant to entail. I am trying my best to keep track of all the AI tool calls that I will make throughout, but the goal is to try to explain how one can use AI tools from Chatbots (Gemini, Claude, etc.), NotebookLM, IDEs (Antigravity, Cursor, etc.), and CLI Agents (Gemini CLI, Claude Code, etc.) to learn something that interests you.


In each section, I will try to have a footnote of the tools that I used to create each plan with a bit of motivation as to what I think. Sections without footnotes like this one I typed, by hand (as hard as it may be to believe).

## Point #1 - You can learn things and skip steps.

I thought about this earlier today, and the quote from Carl Sagan came to mind.

     "If you wish to make an apple pie from scratch, you must first invent the universe,"

---

### Google Search (AI Overview)

I couldn't remember the exact quote so, Googled "carl sagan apple pie", and though I didn't intend to point out every time I did a Google Search, I suppose I did read the overview.

     Answer: Carl Sagan’s famous quote, "If you wish to make an apple pie from scratch, you must first invent the universe," comes from his 1980 series Cosmos. It highlights that all matter, including the ingredients for a pie, is derived from stellar evolution, connecting human existence directly to the cosmos's origin. 
     You can watch this iconic scene from the Cosmos series:

Of course, people do make apple pies, without making the universe, and so, I want to preempt the idea that using AI is somehow cheating, not learning, etc.

When one learns Calculus, there's some helpful lying going on. Anyone who has taken an undergraduate level Real Analysis course can recall being told, "Well, it turns out, that whole thing about area under the curve when letting delta x go to 0? Welll, it doesn't quite work that way, we skimmed over some details. Here's how it *really* works. Let ε > 0, ... "

And then, if you go on to a Graduate level course in Measure Theory, you learn, "Remember when you learned Real Analysis? Turns out we skipped over some steps. Here's how it **really REALLY** works. A *measure* is defined as ..."

I've tutored highschoolers, and let me tell you-- it is often *harmful* to bring up the fact that the integers are a Ring and that subtraction is just addition by the additive inverse-- same for multiplication.

It is true. Some might even think it "more true" than using subtraction or division. But trying to understand everything from first principles is not always the best way to learn.

## Point #2 - It is easy to learn when you are motivated to reach a goal.

I think one of the issues with AI being a firehose of knowledge is when it's used to circumvent the learning process.

Students who are not interested in a subject or just wanting to get "the answer" may not benefit from AI tools, and in fact, the tools make it easier to cheat and not have to learn altogether.

This is, of course, not a new thing with students. When I was in undergrad, I was tutoring an engineering student, and he asked me how to solve some problem.
I looked it over, immediately recognized it as "some very common type of problem," and so I began to highlight how I recognized the pattern and how one could solve any problem of that type.
In the middle of my explanation, the student interrupted me and said, "I don't want to know how to solve this type of problem. I want to know how to solve this problem."
And I realized, I was just helping him do his homework.

The goal for him wasn't to learn; it was to finish all the problems that his teacher had assigned to him.

This is fine, of course. Not everyone has to be motivated to learn everything we're taught in school. But if your goal in school is to get a degree, rather than to learn, then AI tools simply make it easier to skip the learning process.

Since graduating, I have found that I continue to love to learn mathematics, and without the pressure of needing to pass a test or meet some deadline, I get to choose how deep I want to learn a topic.
From first principles? An overview? How some topic relates to the wider field?

I am naturally curious, as most mathematicians are, and so when I was randomly reminded that the abc-conjecture is considered proven in Japan, I figured it would be a good use of AI to create a study plan to try to learn "enough" about the topic that my curiosity would be satisfied.

### Google Search (AI Overview)

I haven't used Jupytenotebooks in a long time; so, I was clicking on the button to add a new section of markdown each time until now. But I love my vim keybindings; so, if possible I try not to use the mouse. Dunno if it's what I'm supposed to do, but I now click `b` to make a new cell and then `m` to turn it into markdown (and then enter to start editing.) Maybe there's a better way, but good enough for now.

Question: shortcut to add markdown in jupyter notebook

    Answer: To add or switch to Markdown in a Jupyter Notebook, use the following keyboard shortcuts while in Command Mode (the cell border will be blue and no blinking cursor is visible): 
    Core Shortcuts
    Convert current cell to Markdown: Press M.
    Convert Markdown back to Code: Press Y.
    Enter Command Mode: Press Esc (required before using M or Y if you are currently typing in a cell).
    Run/Render Markdown cell: Press Shift + Enter. 


## Point #3 - The AI tools are pretty good now

I don't think I could have written this in August of last year. (About 8 months ago.)

The tools were not very good. They hallucinated a lot. There were not many options.

Now there are a lot of great tools. e.g. NotebookLM I think is fantastic at grounding itself in the sources that you provide, forced to cite the lines within the documents you provide with answers to questions that you have.

Many agents can one-shot tasks now. They're smarter, and they are great at idea generation. [Terrance Tao](https://www.youtube.com/watch?v=Q8Fkpi18QXU) uses it and finds them helpful.
IMO, They're a great augment to learning nowadays.
