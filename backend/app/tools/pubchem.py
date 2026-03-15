import requests

from app.core.tooling import ToolExecutionResult, tool_registry


@tool_registry.register(
    name="get_smiles_by_name",
    description="根据化学品名称检索 PubChem 中的标准 Canonical SMILES。适合处理中英文名称、别名与常见俗名。",
    display_name="Querying PubChem Registry…",
    category="retrieval",
    reflection_hint="若检索失败，请尝试英文名、学名、别名或更规范的化学名称；必要时再基于化学知识推导候选结构。",
    output_kinds=("text", "json"),
    tags=("pubchem", "smiles", "lookup"),
)
def get_smiles_by_name(chemical_name: str) -> ToolExecutionResult:
    """
    根据化学品（中英文名称）从 PubChem 数据库获取标准的 SMILES 字符串。
    返回结构化结果，供大模型继续检索、反思或进入绘图流程。
    """
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{chemical_name}/property/CanonicalSMILES/TXT"
    
    try:
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            smiles = response.text.strip()
            return ToolExecutionResult(
                status="success",
                summary=f"已成功查到 '{chemical_name}' 的标准 SMILES。",
                data={
                    "query": chemical_name,
                    "smiles": smiles,
                    "source": "PubChem",
                },
            )
            
        elif response.status_code == 404:
            return ToolExecutionResult(
                status="error",
                summary=f"在 PubChem 数据库中未找到名为 '{chemical_name}' 的物质。",
                data={"query": chemical_name, "source": "PubChem"},
                error_code="not_found",
                retry_hint="请尝试英文名、学名、CAS 相关别名，或修正拼写后重新查询。",
            )
        return ToolExecutionResult(
            status="error",
            summary=f"PubChem API 返回异常状态码 {response.status_code}。",
            data={"query": chemical_name, "source": "PubChem", "status_code": response.status_code},
            error_code="upstream_error",
            retry_hint="请稍后重试，或切换为更规范的化学名称再次检索。",
        )
            
    except requests.exceptions.RequestException as e:
        return ToolExecutionResult(
            status="error",
            summary="请求 PubChem 数据库时发生网络超时或连接错误。",
            data={"query": chemical_name, "source": "PubChem", "detail": str(e)},
            error_code="network_error",
            retry_hint="请稍后重试，若用户名称不标准也可先尝试翻译或规范化后再检索。",
        )

if __name__ == "__main__":
    print("--- 测试 PubChem API (优化版) ---")
    print("1. 测试正确的名称 (Aspirin):")
    print(get_smiles_by_name("Aspirin"))
    
    print("\n2. 测试错误的/不存在的名称 (Unobtanium_Fake_Chemical):")
    print(get_smiles_by_name("Unobtanium_Fake_Chemical"))