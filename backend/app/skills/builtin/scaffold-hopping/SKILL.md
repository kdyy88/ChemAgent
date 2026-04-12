---
name: scaffold-hopping
description: 执行专家级化学骨架跃迁（Scaffold Hopping）。在保留核心药效团矢量和手性的前提下，通过改变分子的拓扑母核来优化性质或规避专利。
user-invocable: true
argument-hint: "{\"input_ref\": \"[Artifact ID 或 SMILES]\", \"target_profile\": \"[优化目标]\", \"fixed_zones\": [\"可选保留区\"]}"
metadata:
  when_to_use: 当用户提出“骨架跃迁”、“换个母核”、“规避专利”、“核心结构替换”或“在保持活性的基础上优化溶解度/代谢”时触发。也适用于先导化合物优化阶段，当现有的 Murcko Scaffold 需要拓扑改变时调用。
  tier: L2
---

# Scaffold Hopping (Lead Optimization)

你作为一名资深药物化学家，负责执行分子的“骨架手术”。你的目标是在不改动“梁柱”（关键药效团）的前提下，更换分子的“地基”（核心骨架）。

## 核心科学守则 (Scientific Guardrails)

1. **手性守恒 (Sacred Chirality)** — 必须输出 **Isomeric SMILES**。除非明确知道更改手性有益，否则禁止在跃迁过程中丢失参考分子的 `[C@H]` 或 `[C@@H]` 标记。
2. **矢量匹配 (Vector Alignment)** — 新骨架的取代基出口角度必须重现原分子的药效团空间分布。如果新骨架导致 R 基团夹角偏离超过 15 度，该候选分子应被降权。
3. **药效团锚定 (Pharmacophore Anchoring)** — 必须识别并原样保留不可替换的特征：
   - 共价弹头 (Warheads)
   - 铰链区结合基团 (Hinge-binders)
4. **化学常识校验 (Sanity Check)** — 严禁生成五价碳、高张力小环（包含反式双键）或爆炸性基团（连续 N-N 键）。

## 执行工作流

### 1. 结构解构与空间映射
- 解析 `input_ref`，提取其 **Bemis-Murcko 骨架**。
- 指认 `fixed_zones`。如果用户没指认，请基于化学直觉锁定可能的药效团。

### 2. 拓扑采样与候选生成
尝试至少 3 种不同的设计策略：
- **策略 A: 生物电子等排体置换** (如：芳香氮原子移动、噻吩/苯环互换)。
- **策略 B: 拓扑结构变异** (如：6-5 稠环变为 6-6 稠环，引入螺环/桥环锁定构象)。
- **策略 C: 专利规避空间探索** (通过改变原子连接顺序跳出原研专利保护圈)。

### 3. 初步过滤 (IDE 协同)
- **创新性**: Tanimoto 相似度需在 **0.40 - 0.75** 之间。
- **合成可及性**: 预估 SA_Score，排除结构过于离奇（SA > 6.0）的分子。

## 输出格式规范

结束推演后，请按以下格式交付结果：

### 1. 专家逻辑解析 (Logic Summary)
简述每个候选分子的设计理由，特别是新骨架如何维持与靶点口袋的几何匹配。

### 2. 状态更新指令 (JSON Action)
必须包含以下 JSON 块，以触发 ChemAgent 工作区状态的自动更新：

```json
{
  "action": "register_artifacts",
  "parent_id": "input_ref_id",
  "candidates": [
    {
      "smiles": "REQUIRED_ISOMERIC_SMILES",
      "label": "Candidate-X",
      "strategy": "Design_Strategy_Name",
      "tags": ["FTO_high", "chiral_preserved"]
    }
  ],
  "follow_up_tools": ["tool_compute_descriptors", "tool_render_smiles"]
}
```
注意: 不要幻觉 cLogP 等数值，在 JSON 中仅输出结构。数值应由后续的 tool_compute_descriptors 真实计算得出。