"""The twelve shipped rules, transcribed as data from the customer's rule book.

Provenance
----------
Thresholds come from ``rules/rule_01…rule_12.md`` supplied by the customer,
cross-checked line-by-line against the twelve production scripts in their
``Application/`` folder. Where the two disagreed, the discrepancy is recorded
in the rule's ``note`` rather than silently resolved — a threshold is an
engineering agreement, and quietly picking one of two conflicting values is
exactly the kind of change that must be visible to the tunnel's own engineers.

Two disagreements were found and are documented on the affected rules:

* **rule_04 (左右底压一致性)** — the rule book gives 150 / 200 / 300 mmH2O; the
  script compares against 30 / 60 / 100 while holding the value in **MPa**
  (the mmH2O conversion sits behind an ``FD == '2'`` branch that the default
  ``FD = '1'`` never takes). The book's numbers are used here, on a value that
  is genuinely in mmH2O.
* **rule_05 (压力传感器零点一致性)** — the book's fourth clause reads
  "差异小于 50 判定正常" while its first clause already calls 30–50 a
  notice-level condition. The three-band structure 30 / 50 / 80 from both the
  book's clauses 1–3 and the script is used; the fourth clause is treated as a
  typo for "小于 30".

The customer's rule 02 mixes two physically distinct faults into one document
(a dead power lead shows up as *too little* code movement, solder/swarf trouble
as *too much*). They are split into ``rule_02a`` / ``rule_02b`` so each has its
own measurable feature — the whole point of separating measurement from
judgement.
"""

from __future__ import annotations

from typing import List

from .rules import Band, Rule

# Citation shorthands reused across rules.
_R = {
    "book": "甲方规则书 rules/*.md（本风洞工程约定，最高优先）",
    "code": "甲方既有实现 Application/*.py（阈值交叉核对）",
    "aiaa_bal": "AIAA R-091-2003《Recommended Practice: Calibration and Use of "
                "Internal Strain-Gage Balances with Application to Wind Tunnel Testing》"
                "—— 天平零点稳定性与回零量是判定天平健康的基本指标",
    "aiaa_unc": "AIAA S-071A-1999《Assessment of Experimental Uncertainty with "
                "Application to Wind Tunnel Testing》—— 系统误差源识别与量化",
    "ptc": "ASME PTC 19.1《Test Uncertainty》—— 仪表零点漂移属于系统误差分量",
    "naca1135": "NACA Report 1135《Equations, Tables, and Charts for Compressible "
                "Flow》eq.(44) —— 等熵总/静压比反算马赫数",
    "gjb": "GJB 1179A-2012《高速风洞和低速风洞流场品质规范》—— 流场马赫数偏差控制要求",
    "iso5725": "ISO 5725《测量方法与结果的准确度(正确度与精密度)》—— 重复性条件下的一致性判定",
}


def seed_rules() -> List[Rule]:
    return [
        # ── 01 天平零飘 ───────────────────────────────────────────────
        Rule(
            rule_id="rule_01_balance_zero_drift",
            name="天平零飘异常诊断",
            feature="balance_zero_drift",
            object_="天平",
            note="天平虚焊、线断或短路会导致零点发生突变，通过连续车次零点监测可识别天平异常。"
                 "本项必须有上一车次的 ca 文件才能评定；连续车次链断开时如实报告「未评定」。",
            refs=[_R["book"], _R["code"], _R["aiaa_bal"], _R["ptc"]],
            bands=[
                Band(level="critical", lo=0.012,
                     verdict="天平零飘超过 0.012，已超出允许范围",
                     cause="天平应变片或引线可能存在虚焊、断线或短路，也可能是天平本体受损。",
                     impact="零点基准失效，本车次及后续车次的六分量测量结果均不可信。",
                     action="建议停止试验并维修天平，复测零点合格后方可继续。"),
                Band(level="warning", lo=0.008, hi=0.012,
                     verdict="天平零飘在 0.008~0.012 之间",
                     cause="天平粘接层或引线接触状态发生变化。",
                     impact="力/力矩测量存在可观的系统偏差，精度指标可能不满足要求。",
                     action="试验人员需检查天平（引线、接头、绝缘），必要时重新标定零点。"),
                Band(level="notice", lo=0.005, hi=0.008,
                     verdict="天平零飘在 0.005~0.008 之间",
                     cause="温度变化或装夹应力释放引起的轻微零点漂移。",
                     impact="对结果影响有限，但趋势需要跟踪。",
                     action="试验人员需引起注意，关注后续车次零飘是否继续增大。"),
                Band(level="ok", hi=0.005, verdict="天平零飘正常"),
            ],
        ),
        # ── 01b 天平零点接近满码 ──────────────────────────────────────
        Rule(
            rule_id="rule_01b_balance_signal_break",
            name="天平信号线断诊断",
            feature="balance_zero_near_17",
            object_="天平信号回路",
            note="任一单元零点读数接近满码 17 时，判定该单元信号线断。"
                 "该判据来自甲方规则书 rule_01 第 1 条。",
            refs=[_R["book"], _R["code"], _R["aiaa_bal"]],
            bands=[
                Band(level="critical", lo=16.0,
                     verdict="存在天平单元零点接近满码 17，判定为天平信号线断",
                     cause="该单元的信号线断开，采集通道读到满量程输出。",
                     impact="该分量完全失效，本车次数据不可用。",
                     action="立即停止试验，检查并修复该单元信号线。"),
                Band(level="ok", hi=16.0, verdict="各单元零点均未接近满码，信号回路正常"),
            ],
        ),
        # ── 02a 天平单元电源线断 ──────────────────────────────────────
        Rule(
            rule_id="rule_02a_balance_power_break",
            name="天平单元电源线断诊断",
            feature="balance_code_span_min",
            object_="天平单元供电回路",
            note="来自甲方规则书 rule_02 第 1 条：跑码量小于 0.0001 判定为电源线断。"
                 "注意甲方 2024-10-14 的注记指出「零点接近零判电源线断易误报」，"
                 "因此本规则以跑码幅值（而非零点绝对值）为判据。",
            refs=[_R["book"], _R["code"], _R["aiaa_bal"]],
            bands=[
                Band(level="critical", hi=0.0001,
                     verdict="存在天平单元跑码幅值小于 0.0001，判定为该单元电源线断",
                     cause="该单元桥路失电，输出恒定不随载荷变化。",
                     impact="该分量无有效测量值，力系数解算结果错误。",
                     action="停止试验，检查天平供电与接线。"),
                Band(level="ok", lo=0.0001, verdict="各单元跑码幅值正常，供电回路正常"),
            ],
        ),
        # ── 02b 天平跑码跳动 ──────────────────────────────────────────
        Rule(
            rule_id="rule_02b_balance_code_jump",
            name="天平跑码异常诊断",
            feature="balance_code_jump",
            object_="天平单元",
            note="天平电源异常会导致跑码幅值异常偏小或偏大；跳动过大多为虚焊或铁屑干扰。",
            refs=[_R["book"], _R["code"], _R["aiaa_bal"]],
            bands=[
                Band(level="warning", lo=0.5,
                     verdict="天平最大跑码跳动量大于 0.5，可能存在虚焊或铁屑干扰",
                     cause="应变片引线虚焊，或天平间隙内落入铁屑造成间歇性短路。",
                     impact="个别攻角点的读数跳变，会污染气动曲线并放大插值误差。",
                     action="建议检修天平：复查焊点，清理天平间隙与支杆腔体。"),
                Band(level="ok", hi=0.5, verdict="天平跑码正常"),
            ],
        ),
        # ── 03 天平回零 ───────────────────────────────────────────────
        Rule(
            rule_id="rule_03_balance_return_zero",
            name="天平回零异常诊断",
            feature="balance_return_zero",
            object_="天平",
            note="天平回零情况是天平工作状态的重要指标。",
            refs=[_R["book"], _R["code"], _R["aiaa_bal"], _R["ptc"]],
            bands=[
                Band(level="critical", lo=0.01,
                     verdict="天平最大不回零量大于 0.01",
                     cause="天平出现塑性变形、粘接层损伤，或装夹存在残余应力未释放。",
                     impact="本车次全部载荷数据带有不可修正的残余偏差。",
                     action="建议停止试验并维修天平。"),
                Band(level="warning", lo=0.006, hi=0.01,
                     verdict="天平最大不回零量在 0.006~0.01 之间",
                     cause="装夹应力释放不充分，或天平接近其弹性极限工作。",
                     impact="载荷数据存在系统偏差，重复性指标下降。",
                     action="试验人员需检查天平与模型装夹状态。"),
                Band(level="notice", lo=0.003, hi=0.006,
                     verdict="天平最大不回零量在 0.003~0.006 之间",
                     cause="正常量级的滞后与温漂。",
                     impact="影响有限。",
                     action="试验人员需引起注意。"),
                Band(level="ok", hi=0.003, verdict="天平回零正常"),
            ],
        ),
        # ── 04 左右底压一致性 ─────────────────────────────────────────
        Rule(
            rule_id="rule_04_base_pressure_lr",
            name="左右底压一致性诊断",
            feature="base_pressure_lr_diff",
            object_="左右底压测量系统",
            note="左右底压理论应接近一致，同时故障概率极低，因此明显不一致基本可判定为测压系统故障。"
                 "【阈值来源说明】采用规则书的 150/200/300 mmH2O；甲方脚本中的 30/60/100 是在未做"
                 "MPa→mmH2O 换算的数值上比较的，量纲不自洽，此处已改为在 mmH2O 上比较。",
            refs=[_R["book"], _R["code"], _R["iso5725"]],
            bands=[
                Band(level="critical", lo=300,
                     verdict="左右底压差最大值大于 300 mmH2O",
                     cause="一侧底压管脱落、堵塞或破裂。",
                     impact="底阻修正失效，轴向力系数 CAF/CAB 严重失真。",
                     action="需停止试验并维修底压管。"),
                Band(level="warning", lo=200, hi=300,
                     verdict="左右底压差最大值在 200~300 mmH2O 之间",
                     cause="底压管存在部分堵塞、渗漏或测压孔加工不对称。",
                     impact="底阻修正引入偏差，影响阻力系数精度。",
                     action="试验人员需检查底压管。"),
                Band(level="notice", lo=150, hi=200,
                     verdict="左右底压差最大值在 150~200 mmH2O 之间",
                     cause="流场轻微不对称或测压管路阻尼差异。",
                     impact="影响有限，但需跟踪。",
                     action="试验人员需引起注意。"),
                Band(level="ok", hi=150, verdict="左右底压一致性正常"),
            ],
        ),
        # ── 05 压力传感器零点一致性 ───────────────────────────────────
        Rule(
            rule_id="rule_05_pressure_zero_spread",
            name="压力传感器零点一致性诊断",
            feature="pressure_zero_spread",
            object_="总压、静压、大气压、左底压、右底压传感器",
            note="试验前所有压力传感器都感受同一大气压，其零点读数理应一致；"
                 "零点不一致将直接影响马赫数计算。"
                 "【阈值来源说明】采用规则书前三条与甲方脚本一致的 30/50/80 mmH2O 三档；"
                 "规则书第 4 条「差异小于 50 判定正常」与第 1 条冲突，按笔误处理。",
            refs=[_R["book"], _R["code"], _R["aiaa_unc"], _R["iso5725"]],
            bands=[
                Band(level="critical", lo=80,
                     verdict="压力传感器零点最大偏差大于 80 mmH2O",
                     cause="某只传感器的 K 值(标定系数)错误或传感器失效。",
                     impact="总静压失准，马赫数与动压计算错误，全部气动系数受影响。",
                     action="需停止试验并修改 K 值后重新标定。"),
                Band(level="warning", lo=50, hi=80,
                     verdict="压力传感器零点最大偏差在 50~80 mmH2O 之间",
                     cause="传感器零点漂移或 K 值偏差。",
                     impact="马赫数计算存在可观偏差。",
                     action="试验人员需检查 K 值。"),
                Band(level="notice", lo=30, hi=50,
                     verdict="压力传感器零点最大偏差在 30~50 mmH2O 之间",
                     cause="温度变化引起的零点轻微漂移。",
                     impact="影响有限。",
                     action="试验人员需引起注意。"),
                Band(level="ok", hi=30, verdict="压力传感器零点一致性正常"),
            ],
        ),
        # ── 06 马赫数一致性（两档，按马赫数分段适用）──────────────────
        Rule(
            rule_id="rule_06a_mach_consistency_low",
            name="来流马赫数一致性诊断（Ma<2.9）",
            feature="mach_deviation",
            object_="风洞流场",
            applies_when_mach="<2.9",
            note="由总静压按等熵关系反算的实际马赫数应与名义马赫数一致，"
                 "偏差过大可识别总静压异常或流场未建立。Ma<2.9 段允许偏差 0.05。",
            refs=[_R["book"], _R["code"], _R["naca1135"], _R["gjb"]],
            bands=[
                Band(level="warning", lo=0.05,
                     verdict="实际吹风马赫数与名义马赫数偏差大于 0.05",
                     cause="总压或静压测量异常，或流场尚未建立/已被扰动。",
                     impact="动压与雷诺数错误，全部气动系数按错误来流条件无量纲化。",
                     action="需检查风洞流场与总静压测量系统。"),
                Band(level="ok", hi=0.05, verdict="来流马赫数一致性正常"),
            ],
        ),
        Rule(
            rule_id="rule_06b_mach_consistency_high",
            name="来流马赫数一致性诊断（Ma≥2.9）",
            feature="mach_deviation",
            object_="风洞流场",
            applies_when_mach=">=2.9",
            note="高马赫数段总静压比大，反算马赫数对压力测量误差更敏感，允许偏差放宽至 0.1。",
            refs=[_R["book"], _R["code"], _R["naca1135"], _R["gjb"]],
            bands=[
                Band(level="warning", lo=0.1,
                     verdict="实际吹风马赫数与名义马赫数偏差大于 0.1",
                     cause="总压或静压测量异常，或流场尚未建立/已被扰动。",
                     impact="动压与雷诺数错误，全部气动系数按错误来流条件无量纲化。",
                     action="需检查风洞流场与总静压测量系统。"),
                Band(level="ok", hi=0.1, verdict="来流马赫数一致性正常"),
            ],
        ),
        # ── 07 底压跑码合理性（两条，方向为“过小才异常”）─────────────
        Rule(
            rule_id="rule_07a_base_vs_atm",
            name="底压跑码合理性诊断（对比大气压）",
            feature="base_vs_atm_min_gap",
            object_="左底压、右底压",
            note="吹风时底压应显著低于大气压；若二者几乎相等，说明底压管堵塞或根本没接上，"
                 "传感器实际测的是大气压。",
            refs=[_R["book"], _R["code"]],
            bands=[
                Band(level="warning", hi=80,
                     verdict="底压与大气压差值小于 80 mmH2O，判定为底压管堵或未接",
                     cause="底压管堵塞、脱落或未连接，传感器读到的是环境大气压。",
                     impact="底阻修正基于错误的底压值，轴向力/阻力系数失真。",
                     action="检查底压管路是否堵塞或未连接，疏通后重测。"),
                Band(level="ok", lo=80, verdict="底压与大气压差值合理"),
            ],
        ),
        Rule(
            rule_id="rule_07b_base_vs_static",
            name="底压跑码合理性诊断（对比来流静压）",
            feature="base_vs_static_min_gap",
            object_="左底压、右底压",
            note="非收缩尾部外形时，底压应明显区别于来流静压；二者过于接近说明底压管漏气或未接。"
                 "尾部为收缩外形时本条不适用，由检查配置中的「尾部收缩外形」开关关闭。",
            refs=[_R["book"], _R["code"]],
            bands=[
                Band(level="warning", hi=60,
                     verdict="底压与来流静压差值小于 60 mmH2O，判定为底压管漏或未接",
                     cause="底压管漏气或未连接，读数被来流静压“拉平”。",
                     impact="底阻修正失真，阻力系数偏差。",
                     action="检查底压管路气密性与连接状态。"),
                Band(level="ok", lo=60, verdict="底压与来流静压差值合理"),
            ],
        ),
        # ── 08 底压突变 ───────────────────────────────────────────────
        Rule(
            rule_id="rule_08_base_pressure_jump",
            name="底压突变异常诊断",
            feature="base_pressure_gradient",
            object_="左右底压测量系统",
            note="底压随攻角的剧烈变化可能由二喉道激波、支杆激波或反射激波扫掠模型尾部引起。"
                 "判据按单位攻角变化率计算，避免攻角间隔不均时的误报"
                 "（沿用甲方 2024-12-13 的修正）。",
            refs=[_R["book"], _R["code"]],
            bands=[
                Band(level="warning", lo=150,
                     verdict="底压跑码突变率大于 150 mmH2O/deg，可能存在激波扫掠尾部",
                     cause="二喉道激波、支杆激波或洞壁反射激波扫过模型底部。",
                     impact="该攻角段的底压不代表真实底部流动，底阻修正不可用。",
                     action="复核该攻角段的底阻修正与数据有效性，必要时调整堵塞度或支撑方案。"),
                Band(level="ok", hi=150, verdict="底压跑码无明显突变"),
            ],
        ),
        # ── 09 弹性变形（三分量）──────────────────────────────────────
        Rule(
            rule_id="rule_09a_elastic_alpha",
            name="模型攻角方向弹性变形诊断",
            feature="elastic_alpha",
            object_="模型与支杆系统",
            note="过大的弹性变形既是结构安全风险，也使名义姿态角与真实姿态角脱节。",
            refs=[_R["book"], _R["code"], _R["aiaa_unc"]],
            bands=[
                Band(level="critical", lo=6.0,
                     verdict="攻角方向弹性变形大于 6°，存在严重危险",
                     cause="气动载荷已使支杆-天平系统产生过大挠曲。",
                     impact="结构存在破坏风险；姿态角修正量过大，数据可信度显著下降。",
                     action="立即降低攻角或动压，必要时更换刚度更高的支撑。"),
                Band(level="warning", lo=4.0, hi=6.0,
                     verdict="攻角方向弹性变形在 4°~6° 之间",
                     cause="载荷较大，支杆挠曲明显。",
                     impact="姿态角修正量大，插值与导数计算误差增大。",
                     action="建议降低攻角。"),
                Band(level="ok", hi=4.0, verdict="攻角方向弹性变形在允许范围内"),
            ],
        ),
        Rule(
            rule_id="rule_09b_elastic_beta",
            name="模型侧滑方向弹性变形诊断",
            feature="elastic_beta",
            object_="模型与支杆系统",
            note="侧滑方向弹性变形直接污染侧向力与偏航力矩。",
            refs=[_R["book"], _R["code"], _R["aiaa_unc"]],
            bands=[
                Band(level="warning", lo=2.0,
                     verdict="侧滑方向弹性变形大于 2.0°",
                     cause="侧向气动载荷过大或支撑侧向刚度不足。",
                     impact="侧向力/偏航力矩测量偏差显著。",
                     action="强烈建议降低侧滑角或动压。"),
                Band(level="notice", lo=1.5, hi=2.0,
                     verdict="侧滑方向弹性变形在 1.5°~2.0° 之间",
                     cause="侧向载荷偏大。",
                     impact="侧向分量存在一定偏差。",
                     action="需注意，关注侧向分量数据的一致性。"),
                Band(level="ok", hi=1.5, verdict="侧滑方向弹性变形在允许范围内"),
            ],
        ),
        Rule(
            rule_id="rule_09c_elastic_gamma",
            name="模型滚转方向弹性变形诊断",
            feature="elastic_gamma",
            object_="模型与支杆系统",
            note="滚转方向弹性变形会改变各分量在体轴系中的投影关系。",
            refs=[_R["book"], _R["code"], _R["aiaa_unc"]],
            bands=[
                Band(level="warning", lo=1.0,
                     verdict="滚转方向弹性变形大于 1.0°，影响显著",
                     cause="滚转力矩较大或支撑抗扭刚度不足。",
                     impact="各分量投影关系失准，法向/侧向分量互相串扰。",
                     action="复核滚转角修正，必要时更换支撑。"),
                Band(level="notice", lo=0.5, hi=1.0,
                     verdict="滚转方向弹性变形在 0.5°~1.0° 之间",
                     cause="滚转载荷偏大。",
                     impact="需考虑其对分量投影的影响。",
                     action="需考虑影响，在数据处理中确认滚转角修正已生效。"),
                Band(level="ok", hi=0.5, verdict="滚转方向弹性变形在允许范围内"),
            ],
        ),
        # ── 10 攻角插值外插 ───────────────────────────────────────────
        Rule(
            rule_id="rule_10_alpha_extrapolation",
            name="攻角插值外插诊断",
            feature="alpha_extrapolation",
            object_="气动数据处理过程",
            note="输出攻角超出实测攻角范围即为外插；严重外插会导致气动数据失真。"
                 "【实现说明】甲方脚本用绝对值计算外插量，纯内插时也会打印很大的数字；"
                 "此处按有符号定义计算，内插一律为 0。",
            refs=[_R["book"], _R["code"]],
            bands=[
                Band(level="warning", lo=2.0,
                     verdict="攻角外插最大角度大于 2°",
                     cause="要求输出的攻角超出了本车次实际吹到的攻角范围。",
                     impact="外插段的气动系数由曲线外推得到，非实测，可信度低。",
                     action="需检查吹风攻角范围，或缩小输出攻角要求。"),
                Band(level="ok", hi=2.0, verdict="攻角插值正常（无显著外插）"),
            ],
        ),
        # ── 11 天平载荷超量程 ─────────────────────────────────────────
        Rule(
            rule_id="rule_11_balance_overload",
            name="天平载荷超量程诊断",
            feature="balance_load_ratio",
            object_="MY、Z、MZ、Y、MX、Q 单元",
            note="超量程会带来结构风险与测量非线性。本项需要该天平在载荷库中的额定量程；"
                 "库中查不到时如实报「未评定」并给出补录入口，不做任何推测。",
            refs=[_R["book"], _R["code"], _R["aiaa_bal"]],
            bands=[
                Band(level="critical", lo=160,
                     verdict="天平载荷占量程超过 160%（超载 60% 以上）",
                     cause="气动载荷远超天平设计量程。",
                     impact="天平可能进入非线性甚至塑性区，存在结构破坏风险，数据不可用。",
                     action="必须采取措施：立即降低动压或攻角，更换更大量程天平。"),
                Band(level="warning", lo=130, hi=160,
                     verdict="天平载荷占量程 130%~160%（超载 30%~60%）",
                     cause="气动载荷超出天平额定量程。",
                     impact="标定公式外推使用，测量不确定度显著增大。",
                     action="需确认结构安全裕度，评估是否继续本状态试验。"),
                Band(level="ok", hi=130, verdict="天平载荷在许可范围内"),
            ],
        ),
        # ── 12 总温传感器 ─────────────────────────────────────────────
        Rule(
            rule_id="rule_12_total_temp_zero",
            name="总温传感器异常诊断",
            feature="total_temp_zero_diff",
            object_="总温传感器、室温传感器",
            note="吹风前总温传感器与室温传感器应读数一致；总温异常将直接影响雷诺数计算。",
            refs=[_R["book"], _R["code"], _R["aiaa_unc"]],
            bands=[
                Band(level="warning", lo=20.0,
                     verdict="总温与室温零点差大于 20 ℃",
                     cause="总温传感器或其变送通道故障、接线错误。",
                     impact="总温错误 → 声速与粘性系数错误 → 雷诺数与马赫数计算失准。",
                     action="需检查总温传感器及其采集通道。"),
                Band(level="ok", hi=20.0, verdict="总温传感器零点正常"),
            ],
        ),
    ]


def seed_rule_dicts() -> List[dict]:
    return [r.to_dict() for r in seed_rules()]
