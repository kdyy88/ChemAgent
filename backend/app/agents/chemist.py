"""Legacy local smoke-test entrypoint.

The production runtime now lives under the Manager + specialists pipeline.
This module is kept only as a lightweight manual test harness.
"""

from app.agents.specialists.visualizer import create_visualizer


def run_local_test(user_prompt: str) -> None:
    print(f"\n--- 开始处理任务: {user_prompt} ---")
    visualizer, executor = create_visualizer()
    executor.initiate_chat(
        visualizer,
        message=user_prompt,
        summary_method="last_msg",
    )


if __name__ == "__main__":
    run_local_test("帮我画一个扑热息痛（对乙酰氨基酚）的结构式。")