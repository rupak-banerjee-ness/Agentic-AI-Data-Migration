"""One-off smoke test for the cracksql editable package (rule-only mode,
no DB/LLM required). Run manually; not part of the pytest suite."""
import os

os.chdir(os.path.join(os.path.dirname(__file__), "..", "tool_adapters", "cracksql_adapter"))
os.makedirs("instance", exist_ok=True)
os.makedirs("logs", exist_ok=True)

from cracksql.cracksql import translate  # noqa: E402

result = translate(
    src_sql="SELECT TOP 10 * FROM employees WHERE ROWNUM <= 10",
    src_dialect="oracle",
    tgt_dialect="postgresql",
)
print("RESULT:", result)
