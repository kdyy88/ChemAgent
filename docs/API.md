# ChemAgent REST API 参考

本文档覆盖所有 HTTP REST 端点。WebSocket 协议（`/api/chat/ws`）见 `ARCHITECTURE.md` 第 4 节。

---

## 公共约定

| 项目 | 说明 |
|------|------|
| 基础 URL | `http://localhost:8000` |
| Content-Type | `application/json` |
| 成功响应 | `200 OK`，body 含 `"is_valid": true` |
| 失败响应 | `200 OK`（业务错误）或 `422`（请求体校验失败），body 含 `"is_valid": false` + `"error": "<原因>"` |

### 通用错误响应结构

```json
{
  "is_valid": false,
  "error": "描述失败原因的字符串"
}
```

---

## 1. RDKit 端点 (总计 6 个)

目前完整支持数据清洗、描述符提取、相似性与子结构警示等 6 大核心 API。以下以最经典的分析端点为例：

### `POST /api/rdkit/analyze` (Legacy 兼容) / `POST /api/rdkit/descriptors`

**功能**：依据 SMILES 字符串提取综合物理化学性质，包括 Lipinski RoF5、TPSA、QED、SA_Score。`analyze` 还会附带 2D 结构图（base64 PNG）。

#### 请求体

```json
{
  "smiles": "CC(=O)Oc1ccccc1C(=O)O",
  "name": "Aspirin"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `smiles` | string | ✅ | 标准 SMILES 字符串 |
| `name` | string | ✅ | 分子名称（仅用于显示，不影响计算） |

#### 成功响应

```json
{
  "type": "lipinski",
  "is_valid": true,
  "name": "Aspirin",
  "smiles": "CC(=O)Oc1ccccc1C(=O)O",
  "properties": {
    "molecular_weight": 180.16,
    "logp": 1.31,
    "hbd": 1,
    "hba": 4,
    "tpsa": 63.6
  },
  "lipinski_pass": true,
  "violations": [],
  "structure_image": "<裸 base64 PNG，无 data: 前缀>"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `"lipinski"` | 固定类型标识 |
| `is_valid` | bool | 是否成功解析 |
| `properties.molecular_weight` | float | 分子量（Da） |
| `properties.logp` | float | 计算 LogP |
| `properties.hbd` | int | 氢键供体数 |
| `properties.hba` | int | 氢键受体数 |
| `properties.tpsa` | float | 拓扑极性表面积（Å²） |
| `lipinski_pass` | bool | 是否满足 Lipinski RoF5（违反数 ≤ 1） |
| `violations` | array | 违反的规则描述列表 |
| `structure_image` | string | 裸 base64 PNG（前端显示时需加 `data:image/png;base64,` 前缀） |

#### curl 示例

```bash
curl -s -X POST http://localhost:8000/api/rdkit/analyze \
  -H "Content-Type: application/json" \
  -d '{"smiles": "CC(=O)Oc1ccccc1C(=O)O", "name": "Aspirin"}' | python3 -m json.tool
```

---

## 2. Open Babel 端点

### `POST /api/babel/convert`

**功能**：将分子在 130+ 种格式之间互转（SMILES、MOL、SDF、InChI、PDB、XYZ 等）。

#### 请求体

```json
{
  "molecule": "CC(=O)Oc1ccccc1C(=O)O",
  "input_format": "smi",
  "output_format": "inchi"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `molecule` | string | ✅ | 输入分子的字符串表示 |
| `input_format` | string | ✅ | 输入格式（见下表） |
| `output_format` | string | ✅ | 输出格式（见下表） |

#### 支持的格式（常用）

| 格式标识 | 说明 |
|----------|------|
| `smi` | SMILES |
| `mol` / `sdf` | MDL MOL / SDF |
| `inchi` | InChI 字符串 |
| `inchikey` | InChIKey |
| `pdb` | PDB 格式 |
| `xyz` | XYZ 坐标格式 |
| `mol2` | Tripos Mol2 |
| `can` | Canonical SMILES |

完整格式列表见 [Open Babel 文档](https://openbabel.org/docs/current/FileFormats/Overview.html)。

#### 成功响应

```json
{
  "type": "format_conversion",
  "is_valid": true,
  "input_format": "smi",
  "output_format": "inchi",
  "output": "InChI=1S/C9H8O4/c1-6(10)13-8-5-3-2-4-7(8)9(11)12/h2-5H,1H3,(H,11,12)",
  "atom_count": 21,
  "heavy_atom_count": 13
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `output` | string | 目标格式的文本内容 |
| `atom_count` | int | 包含氢的原子总数 |
| `heavy_atom_count` | int | 重原子（非氢）数 |

#### curl 示例

```bash
curl -s -X POST http://localhost:8000/api/babel/convert \
  -H "Content-Type: application/json" \
  -d '{"molecule": "CC(=O)Oc1ccccc1C(=O)O", "input_format": "smi", "output_format": "inchi"}' \
  | python3 -m json.tool
```

---

### `POST /api/babel/conformer3d`

**功能**：从 SMILES 生成三维构象，输出 SDF 格式，使用 MMFF94/UFF 力场优化，并返回被优化的力场能量 (`energy_kcal_mol`)。

#### 请求体

```json
{
  "smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
  "name": "caffeine",
  "forcefield": "mmff94",
  "steps": 500
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `smiles` | string | ✅ | — | 分子的 SMILES 字符串 |
| `name` | string | ✅ | — | 分子名称（写入 SDF 标题） |
| `forcefield` | string | ❌ | `"mmff94"` | 力场：`"mmff94"` 或 `"uff"` |
| `steps` | int | ❌ | `500` | 力场优化步数 |

#### 成功响应

```json
{
  "type": "conformer_3d",
  "is_valid": true,
  "name": "caffeine",
  "smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
  "sdf_content": "\n  Open Babel...\n",
  "atom_count": 24,
  "heavy_atom_count": 14,
  "forcefield": "mmff94",
  "steps": 500,
  "has_3d_coords": true
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `sdf_content` | string | 完整 SDF 文件内容，可直接写入 `.sdf` 文件 |
| `has_3d_coords` | bool | 健全性校验：可直接用于下游 3D 工具 |
| `forcefield` | string | 实际使用的力场名称 |
| `steps` | int | 实际使用的优化步数 |

#### curl 示例

```bash
curl -s -X POST http://localhost:8000/api/babel/conformer3d \
  -H "Content-Type: application/json" \
  -d '{"smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "name": "caffeine"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); open('caffeine.sdf','w').write(d['sdf_content'])"
```

---

### `POST /api/babel/pdbqt`

**功能**：从 SMILES 生成 PDBQT 配体文件，用于 AutoDock / Vina 系列分子对接软件。流程：加质子（生理 pH）→ 生成 3D 构象 → Gasteiger 电荷赋值（PDBQT 写入器自动完成）→ 转子检测。

#### 请求体

```json
{
  "smiles": "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
  "name": "ibuprofen",
  "ph": 7.4
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `smiles` | string | ✅ | — | 分子的 SMILES 字符串 |
| `name` | string | ✅ | — | 分子名称（写入 PDBQT 注释） |
| `ph` | float | ❌ | `7.4` | 加质子的目标 pH |

#### 成功响应

```json
{
  "type": "pdbqt_prep",
  "is_valid": true,
  "name": "ibuprofen",
  "smiles": "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
  "pdbqt_content": "REMARK  ...\nATOM   ...\nTORSDOF 5\n",
  "ph": 7.4,
  "rotatable_bonds": 5,
  "heavy_atom_count": 16,
  "total_atom_count": 29,
  "has_root_marker": true,
  "has_torsdof_marker": true,
  "flexibility_warning": false
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `pdbqt_content` | string | 完整 PDBQT 文件内容，可直接传入 Vina |
| `rotatable_bonds` | int | 可旋转键数（来自 TORSDOF 行） |
| `has_root_marker` | bool | 健全性校验：含 ROOT 标记 |
| `has_torsdof_marker` | bool | 健全性校验：含 TORSDOF 标记 |
| `flexibility_warning` | bool | 当 `rotatable_bonds > 10` 时为 `true`，提示构象采样成本较高 |

#### curl 示例

```bash
curl -s -X POST http://localhost:8000/api/babel/pdbqt \
  -H "Content-Type: application/json" \
  -d '{"smiles": "CC(C)Cc1ccc(cc1)C(C)C(=O)O", "name": "ibuprofen", "ph": 7.4}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); open('ibuprofen.pdbqt','w').write(d['pdbqt_content'])"
```

---

## 3. 系统端点

### `GET /health`

**功能**：健康检查。

#### 响应

```json
{
  "status": "ok",
  "allowed_origins": ["*"]
}
```

---

## 4. 错误码速查

| 场景 | HTTP 状态码 | `is_valid` | 常见原因 |
|------|------------|------------|----------|
| 请求体字段缺失或类型错误 | `422` | — | Pydantic 校验失败 |
| SMILES 无效 | `200` | `false` | RDKit/Open Babel 无法解析输入 |
| 不支持的格式 | `200` | `false` | `input_format` 或 `output_format` 不在允许列表内 |
| 3D 构象生成失败 | `200` | `false` | 力场不收敛（罕见，可减少 steps 或换 UFF） |
| 内部异常 | `200` | `false` | `error` 字段含具体 Python 异常信息 |

---

## 5. 前端集成快速参考

前端封装函数位于 [frontend/lib/chem-api.ts](../frontend/lib/chem-api.ts)，对应响应类型位于 [frontend/lib/types.ts](../frontend/lib/types.ts)。

| 函数 | 端点 |
|------|------|
| `analyzeMolecule(smiles, name)` | `POST /api/rdkit/analyze` |
| `convertFormat(molecule, inputFmt, outputFmt)` | `POST /api/babel/convert` |
| `build3DConformer(smiles, name, forcefield?, steps?)` | `POST /api/babel/conformer3d` |
| `preparePdbqt(smiles, name, ph?)` | `POST /api/babel/pdbqt` |

---

### `POST /api/babel/partial-charges`
**功能**：使用 Gasteiger/MMFF94/QEq 等模型计算每个原子的偏电荷。  
**请求体**：`{"smiles": "...", "method": "gasteiger"}`

### `POST /api/babel/sdf-split` 与 `POST /api/babel/sdf-merge`
**功能**：SDF 文件高通量批量处理。支持 `multipart/form-data` 上传，单/多文件分割合并。
**响应**：成功解析后返回内存处理的 `.zip` 打包下载包或 `sdf` 流文本。

