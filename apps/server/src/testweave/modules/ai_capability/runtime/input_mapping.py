from typing import Any

from testweave.core.errors import AppError


def resolve_json_pointer(doc: Any, pointer: str) -> Any:
    """按 RFC 6901 JSON Pointer 安全解析文档片段"""
    if not pointer or pointer == "/":
        return doc

    if not pointer.startswith("/"):
        raise AppError(
            code="RUN_INPUT_SCHEMA_INVALID",
            message=f"非法的 JSON Pointer 格式: {pointer}",
            status_code=400,
        )

    tokens = pointer[1:].split("/")
    curr = doc

    for raw_token in tokens:
        # 解码 RFC 6901 转义字符 ~1 -> /, ~0 -> ~
        token = raw_token.replace("~1", "/").replace("~0", "~")

        if isinstance(curr, dict):
            if token not in curr:
                raise AppError(
                    code="RUN_INPUT_SCHEMA_INVALID",
                    message=f"JSON Pointer 找不到键 '{token}' 在路径 '{pointer}' 中",
                    status_code=400,
                )
            curr = curr[token]
        elif isinstance(curr, list):
            try:
                idx = int(token)
                curr = curr[idx]
            except (ValueError, IndexError) as err:
                raise AppError(
                    code="RUN_INPUT_SCHEMA_INVALID",
                    message=f"JSON Pointer 列表索引 '{token}' 无效或越界 在路径 '{pointer}' 中",
                    status_code=400,
                ) from err
        else:
            raise AppError(
                code="RUN_INPUT_SCHEMA_INVALID",
                message=f"无法对非容器对象执行 JSON Pointer 解析在路径 '{pointer}' 中",
                status_code=400,
            )

    return curr


class InputMappingDSL:
    """P2 节点输入映射解析器 (只支持固定 DSL 引用)"""

    @classmethod
    def parse_reference(cls, ref_str: str) -> tuple[str, str]:
        """解析 引用字符串 -> (source_key, json_pointer)"""
        if "#" in ref_str:
            source, pointer = ref_str.split("#", 1)
        else:
            source, pointer = ref_str, ""

        return source.strip(), pointer.strip()

    @classmethod
    def resolve_mapping(
        cls,
        input_def: Any,
        capability_input: dict[str, Any],
        upstream_outputs: dict[str, dict[str, Any]],
        allowed_upstream_node_ids: set[str],
    ) -> Any:
        """根据节点 input 定义全盘解析得出输入数据"""
        # Case A: 字符串引用
        if isinstance(input_def, str):
            source_key, pointer = cls.parse_reference(input_def)
            source_doc = cls._get_source_doc(
                source_key, capability_input, upstream_outputs, allowed_upstream_node_ids
            )
            return resolve_json_pointer(source_doc, pointer)

        # Case B: 字典映射 (例如 { "req": "capability.input#/req", "human": "human-gate.output" })
        if isinstance(input_def, dict):
            resolved_dict = {}
            for k, v in input_def.items():
                if isinstance(v, str):
                    source_key, pointer = cls.parse_reference(v)
                    source_doc = cls._get_source_doc(
                        source_key, capability_input, upstream_outputs, allowed_upstream_node_ids
                    )
                    resolved_dict[k] = resolve_json_pointer(source_doc, pointer)
                else:
                    # 嵌套递归解构
                    resolved_dict[k] = cls.resolve_mapping(
                        v, capability_input, upstream_outputs, allowed_upstream_node_ids
                    )
            return resolved_dict

        # Case C: 列表解构
        if isinstance(input_def, list):
            return [
                cls.resolve_mapping(
                    item, capability_input, upstream_outputs, allowed_upstream_node_ids
                )
                for item in input_def
            ]

        # 直接常量值
        return input_def

    @classmethod
    def _get_source_doc(
        cls,
        source_key: str,
        capability_input: dict[str, Any],
        upstream_outputs: dict[str, dict[str, Any]],
        allowed_upstream_node_ids: set[str],
    ) -> Any:
        if source_key == "capability.input":
            return capability_input

        if source_key.endswith(".output"):
            node_id = source_key[:-7]
            if node_id not in allowed_upstream_node_ids:
                raise AppError(
                    code="RUN_INPUT_SCHEMA_INVALID",
                    message=f"不能访问非上游节点 '{node_id}' 的输出",
                    status_code=400,
                )
            if node_id not in upstream_outputs:
                raise AppError(
                    code="RUN_INPUT_SCHEMA_INVALID",
                    message=f"上游节点 '{node_id}' 的输出不可用",
                    status_code=400,
                )
            return upstream_outputs[node_id]

        raise AppError(
            code="RUN_INPUT_SCHEMA_INVALID",
            message=f"非法的引用源 '{source_key}'，只支持 'capability.input' 或 '<node-id>.output'",
            status_code=400,
        )
