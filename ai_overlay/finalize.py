"""Finalize technical gates only after real tests/independent verification."""
from pathlib import Path
import hashlib,json
import nbformat
ROOT=Path(__file__).resolve().parents[1]
def main():
 out=ROOT/'output'
 v=json.loads((out/'independent_verification.json').read_text());assert v['passed']
 tests=(out/'unit_tests.txt').read_text();assert '14 passed' in tests
 s=json.loads((out/'execution_receipt.json').read_text());assert s['completed']
 g=json.loads((out/'paper_gate.json').read_text())
 g['technical_tests_independent_verification_pending']=False
 g['technical_checks_pass']=True
 g['ready_for_paper_performance_gate']=g['all_financial_gates_pass'] and g['technical_checks_pass']
 g['paper_trade_enabled']=False
 s.update(unit_tests_passed=14,independent_checks_passed=v['check_count'],paper_trade_enabled=False)
 n=out/'AI_Weekly_Overlay_Executed.ipynb'
 if n.exists():
  nb=nbformat.read(n,as_version=4);cells=[c for c in nb.cells if c.cell_type=='code']
  assert all(c.execution_count is not None and not any(x.output_type=='error' for x in c.outputs) for c in cells)
  s.update(notebook_executed=True,notebook_code_cells=len(cells),notebook_sha256=hashlib.sha256(n.read_bytes()).hexdigest())
 (out/'paper_gate.json').write_text(json.dumps(g,indent=2))
 (out/'execution_receipt.json').write_text(json.dumps(s,indent=2))
 print('Technical checks complete; paper gate:',g['ready_for_paper_performance_gate'],'; paper trading NOT activated')
if __name__=='__main__':main()
