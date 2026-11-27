"""Validate all served pages, consistent navigation, and every inline script."""
import ast
import re
import subprocess
import tempfile
from pathlib import Path
from html.parser import HTMLParser
import ui_layout
import test_lab
class Check(HTMLParser):
    def __init__(self):
        super().__init__();self.ids=set();self.active=[];self.nav=[];self.in_nav=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if "id" in a:
            assert a["id"] not in self.ids,a["id"]
            self.ids.add(a["id"])
        if tag=="nav" and a.get("class")=="pulsar-nav":self.in_nav=True
        if tag=="a" and self.in_nav:
            self.nav.append(a["href"])
            if a.get("aria-current")=="page":self.active.append(a["href"])
    def handle_endtag(self,tag):
        if tag=="nav":self.in_nav=False
src=Path(__file__).with_name("pulsar_dali_control.py").read_text()
names={"PAGE":"overview","COMMISSIONING_PAGE":"commissioning","CONTROLLERS_PAGE":"controllers","REMOTE_PAGE":"remote","DIAGNOSTICS_PAGE":"diagnostics"}
pages={}
for n in ast.parse(src).body:
    if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant):
        for target in n.targets:
            if isinstance(target,ast.Name) and target.id in names:
                k=names[target.id];pages[k]=ui_layout.apply(n.value.value,k)
pages["testlab"]=test_lab.page_for(False);pages["configuration"]=test_lab.page_for(True)
assert len(pages)==7
with tempfile.TemporaryDirectory() as d:
    for key,page in pages.items():
        check=Check();check.feed(page)
        expected=[x[1] for x in ui_layout.PAGES]
        assert check.nav==expected,(key,check.nav)
        assert check.active==[next(x[1] for x in ui_layout.PAGES if x[0]==key)]
        assert "max-width:1440px" in page
        if key in ("overview","commissioning","diagnostics"):
            assert "location.reload()" in page
        for i,s in enumerate(re.findall(r"<script[^>]*>(.*?)</script>",page,re.S)):
            path=Path(d)/f"{key}-{i}.js";path.write_text(s)
            subprocess.run(["node","--check",str(path)],check=True)
        print("UI checked:",key)
assert '<option value="advanced" selected>' in pages["configuration"]
assert '<option value="advanced">' not in pages["testlab"]
assert "paramsFromForm()" in pages["configuration"]

# Test device-based action filtering directly in JavaScript without a browser.
script=re.search(r"<script[^>]*>(.*?)</script>",pages["configuration"],re.S).group(1)
start=script.index("function typesOf(")
end=script.index("const groups=",start)
logic=script[start:end]
checks=r"""
const assert=require("node:assert/strict");
assert(availableActions({kind:"gear",device_type:6}).includes("curve"));
assert(!availableActions({kind:"gear",device_type:6}).includes("color"));
assert(availableActions({kind:"gear",device_type:8}).includes("color"));
assert(!availableActions({kind:"gear",device_type:8}).includes("curve"));
assert.deepEqual(availableActions({kind:"input",instance_type:3}),["input_read","input_config"]);
assert(availableActions({kind:"gear",device_type:1}).includes("emergency_read"));
assert(!availableActions({kind:"gear",device_type:1}).includes("reset"));
assert(!availableActions({kind:"gear",device_type:255,device_types:[1,6]}).includes("restore_apply"));
assert.deepEqual(availableActions(undefined),[]);
"""
subprocess.run(["node","-e",logic+checks],check=True)
