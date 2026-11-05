"""AsisTendero: prototipo de Semana 1."""

from importlib.abc import MetaPathFinder
from importlib.util import find_spec, spec_from_file_location
import sys


class _EvaluateAlias(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "asistendero.evaluate":
            spec = find_spec("asistendero.evaluacion.evaluate")
            if spec is not None and spec.origin is not None:
                return spec_from_file_location(fullname, spec.origin)
        return None


if not any(type(finder).__name__ == "_EvaluateAlias" for finder in sys.meta_path):
    sys.meta_path.insert(0, _EvaluateAlias())

