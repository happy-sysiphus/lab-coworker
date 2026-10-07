"""시연용 합성 매뉴얼 본문 — 실제 제조사 매뉴얼이 아니다. 본실험 과제(스즈키-미야우라 흐름 합성)의 공개 조건 범위에 맞춰 썼다.

허용·권장 범위(spec_range), 관계(promotes·decreases·increases·competes_with), 자동 승인 대상(requires),
어휘에 없는 촉매 이름(XPhos Pd G3 등), 모르는 단위(bar)를 일부러 섞어 온톨로지 에이전트의 게이트·질문을 보여 준다.
"""
TITLE = "Demo Flow Reactor Operating Notes (synthetic)"
HEAD = "Demo Flow Reactor Operating Notes - synthetic document for the LAB GENE demonstration"

PAGES = [
    [HEAD, "Page 1", "",
     "1. Scope",
     "These notes describe how to run palladium-catalysed Suzuki-Miyaura coupling in the droplet flow reactor. "
     "They are a synthetic document written for a demonstration and are not a vendor manual.",
     "",
     "2. Operating limits",
     "The flow reactor temperature must stay between 30 and 110 °C.",
     "The residence time in the flow reactor must stay between 60 and 600 s.",
     "Catalyst loading must stay between 0.5 and 2.5 mol% to protect the downstream filter.",
     "System pressure must not exceed 17 bar during start-up."],
    [HEAD, "Page 2", "",
     "3. Chemistry notes",
     "Suzuki-Miyaura coupling requires a base such as DBU.",
     "Higher temperature promotes protodeboronation of heteroaryl boronic acids.",
     "Protodeboronation decreases reaction yield because the boronic acid is consumed before transmetallation.",
     "Longer residence time increases conversion until the catalyst deactivates.",
     "Carbon-carbon homocoupling reaction competes with Suzuki-Miyaura coupling when oxygen enters the feed.",
     "",
     "4. Recommended window",
     "For heteroaryl boronic acid pinacol esters the recommended temperature is 60 to 100 °C."],
    [HEAD, "Page 3", "",
     "5. Precatalysts",
     "XPhos Pd G3 dissolves quickly in THF and gives the most reproducible activation in this reactor.",
     "SPhos Pd G3 is a good first choice for heteroaryl bromides.",
     "XPhos Pd G3 and SPhos Pd G3 should be stored under nitrogen and weighed fresh for each campaign.",
     "Mesylate precatalysts tolerate water better than chloride precatalysts.",
     "",
     "6. Solvent",
     "THF/water 5:1 is the standard solvent mixture. Degas the water before use."],
    [HEAD, "Page 4", "",
     "7. Maintenance",
     "Flush the reactor with clean THF after every campaign and inspect the droplet generator weekly.",
     "Replace the inlet filter when the pressure drop rises above the value recorded at installation.",
     "Record every deviation in the lab notebook so that the knowledge graph can learn from it."],
]
