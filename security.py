from pathlib import Path

def classify_risk(action):
    a=action.upper()
    if any(x in a for x in ("DELETE","TRANSFER","CHARGE")):return "irreversible"
    if any(x in a for x in ("POST","CREATE","COMMIT","PUSH","UPLOAD","PUBLISH")):return "external_write"
    if any(x in a for x in ("WRITE","UPDATE","EDIT")):return "write"
    return "read"
def safe_path(root,requested):
    base=Path(root).resolve();target=(base/requested).resolve()
    if target!=base and base not in target.parents:raise PermissionError("path escapes sandbox root")
    return target
