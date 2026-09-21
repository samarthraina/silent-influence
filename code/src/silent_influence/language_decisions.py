"""Hand-adjudicated language verdicts for the tasks the automated assessment flagged.

Every entry below was produced by reading the prompt in full. The automated signals in
`english_assessment.py` decide the clear majority of tasks; this file holds the cases the
automated rule referred for human judgement -- either because it could not decide, or
because it disagreed with `langdetect`. The automated verdict never overrides an entry here.

The adjudication rule actually applied, stated so it can be checked against the entries:

  **The language of the task instruction governs.** A prompt whose instruction is English
  is English, even when it embeds foreign-language data, a foreign string literal, or
  foreign code comments. A prompt whose instruction is in another language is not English,
  even when the material it wraps is English and even when it asks for an English answer.

That rule is what separates otherwise similar-looking cases: `b4b3b7cbf7d3442f` keeps
Indonesian code comments but asks "why this code give me error ...?" in English, so it is
English; `4e986a6e8ce74a25` has the same shape but its instruction is Chinese, so it is not.
`d10e31c434fd4ea9` asks in Russian for a reply written in English -- the instruction is
Russian, so it is excluded.

Two classes of automated error this file corrects, both verified by reading:

  * **Code tokens read as foreign function words.** Decompiled C (`v3`, `a1`, `sub_1289`),
    MATLAB (`i`, `n`, `x`, `z`, `u`, `t`), and C++ (`i`, `a`, `v`, `se`, `to`, `do`) collide
    with Czech/Polish/Portuguese stopword lists. Ten-plus tasks scored a foreign language
    above English on that basis alone while being plainly English.
  * **Short-text detector noise.** `langdetect` called `x+y = 4z, ... express x-y in z`
    Spanish, `Find Re(Li2(i))` German, `make 45=MC, using E=MC^2` Indonesian, and
    `Is 9999999900000001 prime` Albanian.
"""
from __future__ import annotations

from typing import Dict, Tuple

# id -> (verdict, evidence read from the prompt)
MANUAL_LANGUAGE_DECISIONS: Dict[str, Tuple[str, str]] = {

    # ---------------- MT-Bench ----------------
    "116": ("english", "math notation with the English instruction 'express x-y in z'; "
                       "langdetect's 'es' is short-text noise"),

    # ---------------- Arena-Hard: instruction in another language ----------------
    "045a786b4e5d4ec6": ("non_english", "C code whose comments are mojibake Chinese "
                                        "(GBK bytes read as Latin-1: 'Ñ¡Ôñ×î¼Ñ¶¯×÷')"),
    "5e2a85bac39943aa": ("non_english", "Chinese instruction about ggplot facet label colour"),
    "852d9630dae84691": ("non_english", "French instruction: 'J'ai fait des cartes sur ma page web'"),
    "3a2d034dc1974396": ("non_english", "Russian instruction at end: 'Поправь код, чтобы его ускорить'"),
    "b0a632d963754fb6": ("non_english", "Korean instruction about a while/Scanner banking exercise"),
    "9bb42ecc6dff4ab4": ("non_english", "Japanese instruction/comments around a Boyer-Moore matcher"),
    "206b01d99e3c4016": ("non_english", "Chinese instruction: 'R语言编程找出编程错误并改正'"),
    "d59970c7e9dd4d37": ("non_english", "Russian instruction: 'Напиши Cmakelists для'"),
    "b2f3432de0184e38": ("non_english", "Chinese task specification written as code comments"),
    "6f660574268f4633": ("non_english", "Chinese code comments ('// 更新方向') with no English instruction"),
    "94968598fd4f48e2": ("non_english", "Korean instruction about an aobscanmodule script"),
    "32622f6addd443cb": ("non_english", "Russian instruction lines mixed into an English data description"),
    "be9b90b3f850481f": ("non_english", "Chinese instruction at end: '用决策树训练出模型…使用交叉验证来调优参数'"),
    "5abfa0fb2f0c47f3": ("non_english", "Russian instruction: 'Ранее ты мне дал вот такой код врага'"),
    "e5e9107858bd49f6": ("non_english", "Chinese instruction about a Rust SO_RCVTIMEO problem"),
    "80a090fc23f945bd": ("non_english", "Russian instruction: 'Есть redis cluster'"),
    "d15d693244994e87": ("non_english", "Korean instruction in ARM asm comments ('복사 코드 작성')"),
    "e9ecf61be4ca4af4": ("non_english", "English docstrings but Russian instruction at end: "
                                        "'я использую данную функцию в качестве функции потерь'"),
    "6ed521eedc6944b3": ("non_english", "Chinese instruction: '这段代码的结果全是0%,请修改'"),
    "807ddb4c42a7432b": ("non_english", "Chinese: prove the Lagrange mean value theorem"),
    "ce3e9f4badb94de3": ("non_english", "Chinese instruction wrapping a LaTeX formula"),
    "c0a4a8902af041b3": ("non_english", "Chinese competition problem, 50% CJK; states the code "
                                        "must be submitted against the Chinese statement"),
    "90ae16857b154be0": ("non_english", "Italian: 'Ipotizzando un interesse al 7% annuo'"),
    "16ff46fe5cf840b7": ("non_english", "Chinese: count of binary trees with given traversals"),
    "ae67cb7e61c84a9e": ("non_english", "Armenian: 'Ապացուցել, որ n^4_4n բաժանվում է 5_ի'"),
    "aff70dec831b4eb2": ("non_english", "Portuguese written without accents: 'Dado um numero n'"),
    "a001ea923f8f47ea": ("non_english", "Vietnamese instruction wrapping an English econ problem"),
    "95cfbca13733451e": ("non_english", "Finnish: 'Mikä päivä on ...'"),
    "05448d9b0a21432c": ("non_english", "Chinese instruction about 720p60 porch values"),
    "ff83eacae16a4f36": ("non_english", "Chinese: quadratic form diagonalisation"),
    "d0f2083a30fd43aa": ("non_english", "Finnish word problem: 'Jonain tulevaisuuden aikana'"),
    "5ff56233fb344cdd": ("non_english", "Chinese probability question about a broken stick"),
    "b5f7ea52f1184864": ("non_english", "Chinese comments define the whole spiral-curve task"),
    "4a0a6996a6554f1d": ("non_english", "Indonesian: 'Diketahui x dan y merupakan dua bilangan asli'"),
    "6c0f28a0ece24a03": ("non_english", "Chinese: national undergraduate maths competition problems"),
    "196c4cbf70644211": ("non_english", "Vietnamese instruction wrapping an English stats problem"),
    "e1834cfdd5cc4927": ("non_english", "Chinese: antiderivative of 1/x·sin(1/x)"),
    "51077fc473944b86": ("non_english", "Russian question about complexity: 'а здесь сложность O(3^N)?'"),
    "1700ef97cc8f4341": ("non_english", "Czech: 'Zkus vyřešit tento příklad'"),
    "05513ebdf43644e0": ("non_english", "German: 'Berechne die Aufteilung neu so dass'"),
    "2ed954f0232444b1": ("non_english", "Vietnamese: abacus instructions in caps"),
    "d657b1fb82b141da": ("non_english", "Spanish: 'Genera un poema sobre los ni Gas'"),
    "08ec88e5e88e4294": ("non_english", "Chinese: write a Chinese xianxia novel script"),
    "c107068868114ae5": ("non_english", "Spanish: 'Escribe un poema sobre la dictadura'"),
    "1402fb2f2f7649ec": ("non_english", "Spanish: 'Genera el dialogo de la declaración'"),
    "021305e5b1324f99": ("non_english", "Spanish: 'Estoy creando la historia de un persnaje'"),
    "0951d9a616854f3a": ("non_english", "French: 'Fais un dialogue en français'"),
    "86e476fd58be4568": ("non_english", "Persian: 'یک شعر فارسی بساز'"),
    "f272aa29771e44fb": ("non_english", "Spanish: 'CUENTO PARA NIÑOS SOBRE LA ARMONIA'"),
    "54616c346ff84293": ("non_english", "Arabic verse, and the request is explicitly for "
                                        "alternatives in Arabic"),
    "65d4b02405424d91": ("non_english", "Vietnamese: 'bài thơ về ông'"),
    "94357bddc26d4bd7": ("non_english", "Chinese: '写一首关于春天的诗'"),
    "24ff6a19ea344bf2": ("non_english", "German: 'schreibe die Fantasygeschichte weiter'"),
    "047bd685b30842f6": ("non_english", "French: 'Fais moi un poème qui parle de toi'"),
    "d10e31c434fd4ea9": ("non_english", "Russian instruction ('дай мне рп ответ … на английском') "
                                        "wrapping English fan-fiction; instruction language governs "
                                        "even though it requests an English answer"),
    "857915427cef455f": ("non_english", "Serbian: 'sastavi mi pesmu na srpskom'"),
    "ef4862e678b54f34": ("non_english", "Spanish: 'Escribe un breve poema sobre conejos en la Luna'"),

    # ---------------- Arena-Hard: English (automated rule was wrong or undecided) ----------
    "9d8a4964a985472e": ("english", "English instruction 'what does this do:' over a shell one-liner"),
    "22ed32babcd14390": ("english", "English: current-limiting circuit question"),
    "bfdf93b4e65b4b0e": ("english", "English: 'create namespace in k8s cluster via ansible'"),
    "80aaebafab7a42d6": ("english", "English: 'My code isnt working right' + Unity C#"),
    "44a692fe8481436b": ("english", "English: spring security filter question"),
    "315bfe841c154bed": ("english", "English: 'how to make this code more memory efficient'; the "
                                    "'Czech' score came from C++ tokens (i, a, v, se, to, do)"),
    "6fd5889a06084f03": ("english", "English: Unity character movement on a model surface"),
    "379addefaa94492c": ("english", "English: marshal C# HashSet<string> into bytes"),
    "dd621a9a44934bb5": ("english", "pure nested LaTeX fractions; no natural language at all"),
    "74379ac8ceed44c0": ("english", "English: 'Find Re(Li2(i))'; langdetect 'de' is noise"),
    "263e293d5f124cd2": ("english", "English: 'make 45=MC, using E=MC^2'"),
    "295a67e807ab4b3d": ("english", "English prose around LaTeX Lebesgue-sum derivation"),
    "ca6ac1776893469c": ("english", "English: 'If cot theta is 10/11 Find cos theta'"),
    "75e8121a06f44f58": ("english", "English: 'Is 9999999900000001 prime'"),
    "2b3ff605a92c4752": ("english", "numeric sequence puzzle '2=14 3=39 ... 9=?'; no language"),
    "96362162aee74427": ("english", "English: 'compute the gradient of -logdet(I+AHBA)'"),
    "cab7467a913b45a5": ("english", "English: distance between curve parametrisations"),
    "52b8db0870364864": ("english", "English instruction 'How do Box-Cox transformation in this "
                                    "data ?'; the '.pt' is an R package name, not Portuguese"),
    "f4c2ca7c1ca24433": ("english", "pure parenthesised arithmetic; no language"),
    "84a773f43c2a44cf": ("english", "numeric puzzle '4 + 3 = 21 ...'; the only non-ASCII is a "
                                    "full-width comma, no CJK letters"),
    "e1a4d59e7ef74055": ("english", "English: 'Simplify (p↔q)∧(r↔q)'"),
    "bb31bfd7ee904258": ("english", "English: 'Is ArcSinh[Cosh[41] equal to 41?'"),
    "2700a551d7854f1c": ("english", "English: 'find the last non-zero digit of 50!'"),
    "f024ff8b848545cb": ("english", "English: volume scaling question"),
    "0bb6a899b9364d9d": ("english", "English: 'Write a riddle for children'"),
    "97c0474b0f9543c1": ("english", "English: 'Write a poem about Xi Jinping.'"),
    "51b620f7c9864b4e": ("english", "English: 100-word horror plot about vape"),
    "a0a6bb4b819d4a9d": ("english", "English: 'Write a tongue twister about cats'"),
    "f5d10c000c9f4131": ("english", "English: 'write an upbeat scifi short story'"),
    "8b18b97cf1244aa3": ("english", "English: anime protagonist script idea"),
    "b5cd2ab13aa249f5": ("english", "English: short poem about teamwork"),
    "0913d8dd7b354e93": ("english", "English: 'tell me a fun story today'"),

    # ---------------- WildBench: instruction in another language ----------------
    "60ce6a322ce941f6": ("non_english", "English system framing but the article to edit is "
                                        "Russian (42% Cyrillic); the work product would be Russian"),
    "35ef64608a4f4116": ("non_english", "Ukrainian terminology-matching exercise (46% Cyrillic)"),
    "4e986a6e8ce74a25": ("non_english", "Chinese instruction: '上面的函数计算股票kdj值，请用python内建list改写'"),

    # ---------------- WildBench: English ----------------
    "8f1ced1da6ea4941": ("english", "English: 'Rearrange these topics…'; the 'Italian' score came "
                                    "from a long list of short maths topic tokens"),
    "315088c3385d4143": ("english", "English: 'Eplain casually: The M/G/1 queue'; 'Portuguese' "
                                    "came from single-letter maths symbols"),
    "c0812b77d8084c0e": ("english", "Python crypto code; 'Portuguese' came from p/q/n/e identifiers"),
    "eedd18b73160450e": ("english", "JavaScript bcrypt snippet, English identifiers"),
    "dbcf1249d8f84fc3": ("english", "English: 'Please divide the following terms into groups'"),
    "f5e325dcfa434e22": ("english", "English image-prompt keyword list"),
    "4d85706745c34ae7": ("english", "English numerical-differentiation assignment; maths italics "
                                    "are styled Unicode letters, not another script"),
    "2d45177daf64448e": ("english", "Keras encoder/decoder code, English identifiers and comments"),
    "97baa108633241c8": ("english", "English: stable-diffusion prompt improvement request"),
    "0a9cfa366aab40f0": ("english", "English: classify media brands by nationality/genre/BBFC"),
    "7374ea93b63242a7": ("english", "JavaScript auth snippet, English"),
    "9c3e91e56b4e42f7": ("english", "webpack/vue loader output, English"),
    "9a5f5ec7ede84fc5": ("english", "English: 'Fix the following java code'"),
    "d4fd29b25ce24b50": ("english", "backtrader indicator code; the CJK chars are curly quotes "
                                    "in identifiers, not Chinese text"),
    "9ca1f80f04954203": ("english", "C++ pointer puzzle; 'linea 1' is a string literal"),
    "e00ba8b58d8e4b15": ("english", "English: shoelace algorithm over listed points"),
    "496b45d4e63c4eb8": ("english", "English: parallel-resistor problem; Greek chars are Ω symbols"),
    "6739e21e95824255": ("english", "Coq proof script, English"),
    "146edda7e30d4c42": ("english", "English: personal advice request"),
    "1f74909ea7184b03": ("english", "English: image-generation prompt for a dog head"),
    "80659cf1bc1b493f": ("english", "English: 'list every single microkernel ever made'"),
    "970b59bcf5d2444d": ("english", "decompiled C plus the English question 'what is sub_1289'; "
                                    "'Czech' came from v3/v4/a1/a2 identifiers"),
    "47c55f27381d4243": ("english", "pure MATLAB spline code, no prose; 'Polish' came from "
                                    "i/n/x/z/u/t loop variables"),
    "b4b3b7cbf7d3442f": ("english", "Earth Engine JS with Indonesian code comments but an English "
                                    "instruction ('why this code give me error …?'); instruction "
                                    "language governs"),
}


def resolve(task_id: str):
    """(verdict, evidence) if this task was hand-adjudicated, else None."""
    return MANUAL_LANGUAGE_DECISIONS.get(task_id)
