# backend/app/tools/rdkit_ui.py
import base64
from io import BytesIO

from rdkit import Chem
from rdkit.Chem import Draw

from app.core.tooling import ToolArtifact, ToolExecutionResult, tool_registry


@tool_registry.register(
    name="generate_2d_image_from_smiles",
    description="将标准 SMILES 转换为高质量 2D 分子结构图，并以 PNG Base64 产物返回。可选传入化合物名称 name 用于标注图片标题。",
    display_name="Generating 2D Structure…",
    category="visualization",
    reflection_hint="若 RDKit 解析失败，请重新检查环闭合、芳香性、原子价态与括号层级，修正 SMILES 后重试。",
    output_kinds=("image", "json"),
    tags=("rdkit", "image", "smiles"),
)
def generate_2d_image_from_smiles(smiles: str, name: str = "") -> ToolExecutionResult:
    """
    接收 SMILES 字符串，使用 RDKit 解析并生成 2D 图像。
    name 可选，传入化合物名作为图片标题（如 "Aspirin"）。
    成功时返回结构化图片产物；失败时返回可用于反思的化学解析错误。
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
        
        if mol is None:
            return ToolExecutionResult(
                status="error",
                summary=f"RDKit 无法解析 SMILES: {smiles}",
                data={"smiles": smiles},
                error_code="invalid_smiles",
                retry_hint="请检查环闭合、芳香性、括号匹配和原子价态，修正后再重新绘图。",
            )
            
        img = Draw.MolToImage(mol, size=(400, 400))
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        return ToolExecutionResult(
            status="success",
            summary="已成功生成 2D 分子结构图。",
            data={"smiles": smiles, "image_format": "png"},
            artifacts=[
                ToolArtifact(
                    kind="image",
                    mime_type="image/png",
                    data=img_base64,
                    encoding="base64",
                    title=name.strip() if name and name.strip() else smiles,
                    description=f"RDKit generated structure for {name or smiles}",
                )
            ],
        )
        
    except Exception as e:
        return ToolExecutionResult(
            status="error",
            summary="RDKit 工具发生未知异常。",
            data={"smiles": smiles, "detail": str(e)},
            error_code="rdkit_exception",
            retry_hint="请确认输入是标准 SMILES；若仍失败，可先重新检索更权威的结构来源。",
        )

if __name__ == "__main__":
    print("--- 测试 RDKit 绘图工具 ---")
    
    print("1. 测试正确的 SMILES (阿司匹林):")
    result_success = generate_2d_image_from_smiles("CC(=O)OC1=CC=CC=C1C(=O)O")
    # 截取前 50 个字符展示，避免刷屏
    print(f"返回结果前50个字符: {result_success[:50]}... (总长度: {len(result_success)})") 
    
    print("\n2. 测试错误的 SMILES (故意制造化合价错误，C大写改小写导致芳香环破坏):")
    result_fail = generate_2d_image_from_smiles("CC(=O)OC1=cc=CC=C1C(=O)O")
    print(result_fail)