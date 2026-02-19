"""Service interface extractor using tree-sitter AST pattern matching.

Extracts HTTP endpoints, event publish/subscribe patterns, and exported symbols
from source code across Python (FastAPI, Flask), TypeScript (Express, NestJS),
C# (ASP.NET), and Go (net/http) frameworks.

Uses AST-based pattern matching (REQ-032) rather than regex on strings.
"""
from __future__ import annotations

import logging
from typing import Any

from src.codebase_intelligence.services.ast_parser import ASTParser
from src.codebase_intelligence.services.symbol_extractor import SymbolExtractor
from src.shared.models.codebase import ServiceInterface, SymbolDefinition, SymbolKind, Language

logger = logging.getLogger(__name__)

# HTTP methods recognized across all frameworks.
_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}

# Python route decorator object names (e.g. @app.get, @router.post).
_PYTHON_ROUTE_OBJECTS = {"app", "router", "api", "blueprint", "bp"}

# Python Flask-style @app.route / @blueprint.route attribute name.
_PYTHON_ROUTE_ATTR = "route"

# TypeScript Express-style caller object names.
_TS_EXPRESS_OBJECTS = {"app", "router", "server"}

# NestJS decorator names -> HTTP method.
_NESTJS_DECORATORS = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Delete": "DELETE",
    "Patch": "PATCH",
    "Head": "HEAD",
    "Options": "OPTIONS",
}

# ASP.NET attribute names -> HTTP method.
_ASPNET_ATTRIBUTES = {
    "HttpGet": "GET",
    "HttpPost": "POST",
    "HttpPut": "PUT",
    "HttpDelete": "DELETE",
    "HttpPatch": "PATCH",
    "HttpHead": "HEAD",
    "HttpOptions": "OPTIONS",
    "Route": None,  # Route attribute without explicit method
}

# Python event emitter / message broker patterns.
_PYTHON_PUBLISH_METHODS = {"emit", "publish", "send", "send_event", "dispatch", "produce"}
_PYTHON_CONSUME_METHODS = {"on", "subscribe", "consume", "listen", "handle", "on_event"}

# TypeScript event patterns.
_TS_PUBLISH_METHODS = {"emit", "publish", "send", "dispatch", "produce"}
_TS_CONSUME_METHODS = {"on", "subscribe", "addEventListener", "consume", "listen"}


class ServiceInterfaceExtractor:
    """Extract service interface information from source code using AST analysis.

    Detects HTTP endpoints, event publish/subscribe patterns, and exported
    symbols using tree-sitter ASTs for pattern matching (REQ-032).

    Supported frameworks:
    - Python: FastAPI (@app.get/post/put/delete), Flask (@app.route)
    - TypeScript: Express (app.get/post), NestJS (@Get/@Post/@Put/@Delete)
    - C#: ASP.NET ([HttpGet], [HttpPost], [HttpPut], [HttpDelete])
    - Go: net/http (http.HandleFunc)
    """

    def __init__(self, ast_parser: ASTParser, symbol_extractor: SymbolExtractor) -> None:
        self._ast_parser = ast_parser
        self._symbol_extractor = symbol_extractor

    def extract(self, source: bytes, file_path: str, service_name: str) -> ServiceInterface:
        """Extract the service interface from a source file.

        Parameters
        ----------
        source:
            Raw source bytes of the file.
        file_path:
            Path to the source file (used for language detection).
        service_name:
            Name of the service this file belongs to.

        Returns
        -------
        ServiceInterface
            Contains endpoints, events_published, events_consumed, and
            exported_symbols extracted from the source code.
        """
        language = self._ast_parser.detect_language(file_path)
        if language is None:
            logger.debug("Unsupported file extension for %s, returning empty interface", file_path)
            return ServiceInterface(service_name=service_name)

        try:
            parse_result = self._ast_parser.parse_file(source, file_path)
        except (ValueError, AttributeError, KeyError):
            logger.warning("Failed to parse %s, returning empty interface", file_path, exc_info=True)
            return ServiceInterface(service_name=service_name)

        tree = parse_result["tree"]
        raw_symbols = parse_result["symbols"]
        root = tree.root_node

        # Extract endpoints based on language.
        endpoints = self._extract_endpoints(root, language, source)

        # Extract event patterns based on language.
        events_published: list[dict[str, Any]] = []
        events_consumed: list[dict[str, Any]] = []
        self._extract_events(root, language, source, events_published, events_consumed)

        # Convert raw symbols to SymbolDefinition instances via SymbolExtractor.
        exported_symbols = self._symbol_extractor.extract_symbols(
            raw_symbols=raw_symbols,
            file_path=file_path,
            language=language,
            service_name=service_name,
        )
        # Filter to only exported symbols.
        exported_symbols = [s for s in exported_symbols if s.is_exported]

        logger.debug(
            "Extracted %d endpoints, %d published events, %d consumed events, "
            "%d exported symbols from %s",
            len(endpoints),
            len(events_published),
            len(events_consumed),
            len(exported_symbols),
            file_path,
        )

        return ServiceInterface(
            service_name=service_name,
            endpoints=endpoints,
            events_published=events_published,
            events_consumed=events_consumed,
            exported_symbols=exported_symbols,
        )

    # ------------------------------------------------------------------
    # Endpoint extraction dispatch
    # ------------------------------------------------------------------

    def _extract_endpoints(
        self, root: Any, language: str, source: bytes
    ) -> list[dict[str, Any]]:
        """Dispatch endpoint extraction to the correct language handler."""
        if language == "python":
            return self._extract_python_endpoints(root, source)
        elif language == "typescript":
            return self._extract_typescript_endpoints(root, source)
        elif language == "csharp":
            return self._extract_csharp_endpoints(root, source)
        elif language == "go":
            return self._extract_go_endpoints(root, source)
        return []

    # ------------------------------------------------------------------
    # Python endpoint extraction (REQ-013)
    # ------------------------------------------------------------------

    def _extract_python_endpoints(
        self, root: Any, source: bytes
    ) -> list[dict[str, Any]]:
        """Extract HTTP endpoints from Python source using AST walking.

        Detects patterns:
        - FastAPI: @app.get("/path"), @router.post("/path"), etc.
        - Flask: @app.route("/path", methods=["GET"]), @blueprint.route(...)
        """
        endpoints: list[dict[str, Any]] = []
        self._walk_python_node(root, endpoints, source)
        return endpoints

    def _walk_python_node(
        self, node: Any, endpoints: list[dict[str, Any]], source: bytes
    ) -> None:
        """Recursively walk a Python AST looking for decorated definitions."""
        if node.type == "decorated_definition":
            self._check_python_decorated(node, endpoints, source)

        for child in node.children:
            self._walk_python_node(child, endpoints, source)

    def _check_python_decorated(
        self, decorated_node: Any, endpoints: list[dict[str, Any]], source: bytes
    ) -> None:
        """Check if a decorated_definition has route decorators."""
        # Find the handler function/class name.
        handler_name = self._find_python_handler_name(decorated_node)

        # Iterate over decorator children.
        for child in decorated_node.children:
            if child.type == "decorator":
                endpoint = self._parse_python_decorator(child, handler_name, source)
                if endpoint is not None:
                    endpoints.append(endpoint)

    def _parse_python_decorator(
        self, decorator_node: Any, handler_name: str, source: bytes
    ) -> dict[str, Any] | None:
        """Parse a single Python decorator node for route information.

        Looks for patterns like:
        - @app.get("/path")        -> method=GET, path=/path
        - @router.post("/path")    -> method=POST, path=/path
        - @app.route("/path", methods=["GET"])  -> method=GET, path=/path
        """
        # The decorator node contains: "@" and then either a call or attribute.
        # Find the call expression inside the decorator.
        call_node = self._find_child_of_type(decorator_node, "call")
        if call_node is None:
            # Check for bare decorator without call (e.g., @app.get without parens)
            # This is unusual for route decorators but handle gracefully.
            return None

        # The function being called (e.g., app.get, router.post, app.route).
        func_node = call_node.child_by_field_name("function")
        if func_node is None:
            return None

        # We expect an attribute access: object.method
        if func_node.type == "attribute":
            obj_node = func_node.child_by_field_name("object")
            attr_node = func_node.child_by_field_name("attribute")
            if obj_node is None or attr_node is None:
                return None

            obj_name = obj_node.text.decode()
            attr_name = attr_node.text.decode()

            # Check if this is a known route object.
            if obj_name not in _PYTHON_ROUTE_OBJECTS:
                return None

            method: str | None = None
            path = ""

            if attr_name.lower() in _HTTP_METHODS:
                # FastAPI style: @app.get("/path")
                method = attr_name.upper()
                path = self._extract_python_first_string_arg(call_node, source)
            elif attr_name == _PYTHON_ROUTE_ATTR:
                # Flask style: @app.route("/path", methods=["GET"])
                path = self._extract_python_first_string_arg(call_node, source)
                method = self._extract_python_methods_kwarg(call_node, source)
                if method is None:
                    method = "GET"  # Flask defaults to GET
            else:
                return None

            return {
                "method": method,
                "path": path,
                "handler": handler_name,
                "line": decorator_node.start_point[0] + 1,
            }

        return None

    @staticmethod
    def _find_python_handler_name(decorated_node: Any) -> str:
        """Find the function or class name inside a decorated_definition."""
        for child in decorated_node.children:
            if child.type in ("function_definition", "class_definition"):
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    return name_node.text.decode()
        return "<unknown>"

    @staticmethod
    def _extract_python_first_string_arg(call_node: Any, source: bytes) -> str:
        """Extract the first string literal argument from a call node.

        Handles both single and double-quoted strings, including f-strings
        with static content.
        """
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            return ""

        for child in args_node.named_children:
            if child.type == "string":
                raw = child.text.decode()
                # Strip quotes (single, double, triple-quoted).
                return _strip_python_string(raw)
            # Handle concatenated string as first arg.
            if child.type == "concatenated_string":
                parts: list[str] = []
                for part in child.named_children:
                    if part.type == "string":
                        parts.append(_strip_python_string(part.text.decode()))
                return "".join(parts)
            # If the first positional arg is not a string, stop.
            if child.type != "keyword_argument":
                break

        return ""

    @staticmethod
    def _extract_python_methods_kwarg(call_node: Any, source: bytes) -> str | None:
        """Extract the HTTP method from a methods=["GET"] keyword argument."""
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            return None

        for child in args_node.named_children:
            if child.type == "keyword_argument":
                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")
                if name_node is None or value_node is None:
                    continue
                if name_node.text.decode() == "methods":
                    # Value is typically a list: ["GET"] or ["GET", "POST"]
                    # Return the first method found.
                    return _extract_first_string_from_list(value_node)

        return None

    # ------------------------------------------------------------------
    # TypeScript endpoint extraction (REQ-013, REQ-014)
    # ------------------------------------------------------------------

    def _extract_typescript_endpoints(
        self, root: Any, source: bytes
    ) -> list[dict[str, Any]]:
        """Extract HTTP endpoints from TypeScript source using AST walking.

        Detects patterns:
        - Express: app.get("/path", handler), router.post("/path", handler)
        - NestJS: @Get("/path"), @Post("/path"), @Put("/path"), @Delete("/path")
        """
        endpoints: list[dict[str, Any]] = []
        self._walk_ts_node(root, endpoints, source)
        return endpoints

    def _walk_ts_node(
        self, node: Any, endpoints: list[dict[str, Any]], source: bytes
    ) -> None:
        """Recursively walk a TypeScript AST looking for endpoint patterns."""
        if node.type == "call_expression":
            endpoint = self._check_ts_express_call(node, source)
            if endpoint is not None:
                endpoints.append(endpoint)

        # NestJS decorators appear as decorator nodes in TypeScript.
        if node.type == "decorator":
            endpoint = self._check_ts_nestjs_decorator(node, source)
            if endpoint is not None:
                endpoints.append(endpoint)

        for child in node.children:
            self._walk_ts_node(child, endpoints, source)

    def _check_ts_express_call(
        self, call_node: Any, source: bytes
    ) -> dict[str, Any] | None:
        """Check if a call_expression is an Express-style route registration.

        Patterns: app.get("/path", handler), router.post("/path", handler)
        """
        func_node = call_node.child_by_field_name("function")
        if func_node is None or func_node.type != "member_expression":
            return None

        obj_node = func_node.child_by_field_name("object")
        prop_node = func_node.child_by_field_name("property")
        if obj_node is None or prop_node is None:
            return None

        obj_name = obj_node.text.decode()
        prop_name = prop_node.text.decode()

        # Check for Express pattern: app.get, router.post, etc.
        if obj_name not in _TS_EXPRESS_OBJECTS:
            return None
        if prop_name.lower() not in _HTTP_METHODS:
            return None

        path = self._extract_ts_first_string_arg(call_node, source)
        handler = self._extract_ts_handler_name(call_node, source)

        return {
            "method": prop_name.upper(),
            "path": path,
            "handler": handler,
            "line": call_node.start_point[0] + 1,
        }

    def _check_ts_nestjs_decorator(
        self, decorator_node: Any, source: bytes
    ) -> dict[str, Any] | None:
        """Check if a decorator is a NestJS route decorator.

        Patterns: @Get("/path"), @Post("/path"), @Put(), @Delete()
        """
        # The decorator contains a call_expression or just an identifier.
        # NestJS: @Get("/path") -> decorator > call_expression
        # or @Get -> decorator > identifier
        for child in decorator_node.children:
            if child.type == "call_expression":
                func_node = child.child_by_field_name("function")
                if func_node is None:
                    continue
                func_name = func_node.text.decode()
                if func_name in _NESTJS_DECORATORS:
                    method = _NESTJS_DECORATORS[func_name]
                    path = self._extract_ts_first_string_arg(child, source)
                    handler = self._find_ts_decorated_method_name(decorator_node)
                    return {
                        "method": method,
                        "path": path,
                        "handler": handler,
                        "line": decorator_node.start_point[0] + 1,
                    }
            elif child.type == "identifier":
                func_name = child.text.decode()
                if func_name in _NESTJS_DECORATORS:
                    method = _NESTJS_DECORATORS[func_name]
                    handler = self._find_ts_decorated_method_name(decorator_node)
                    return {
                        "method": method,
                        "path": "",
                        "handler": handler,
                        "line": decorator_node.start_point[0] + 1,
                    }

        return None

    @staticmethod
    def _extract_ts_first_string_arg(call_node: Any, source: bytes) -> str:
        """Extract the first string literal argument from a TS call expression."""
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            return ""

        for child in args_node.named_children:
            if child.type == "string":
                raw = child.text.decode()
                return _strip_js_string(raw)
            if child.type == "template_string":
                raw = child.text.decode()
                return _strip_template_string(raw)
            # Stop at first non-string argument.
            break

        return ""

    @staticmethod
    def _extract_ts_handler_name(call_node: Any, source: bytes) -> str:
        """Extract the handler name from the second argument of an Express call.

        E.g., app.get("/path", myHandler) -> "myHandler"
              app.get("/path", (req, res) => {...}) -> "<anonymous>"
        """
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            return "<anonymous>"

        named_children = args_node.named_children
        # The handler is typically the second (or last) argument.
        for child in named_children[1:]:
            if child.type == "identifier":
                return child.text.decode()
            if child.type == "member_expression":
                return child.text.decode()
            # Arrow function or function expression -> anonymous.
            if child.type in ("arrow_function", "function"):
                return "<anonymous>"

        return "<anonymous>"

    @staticmethod
    def _find_ts_decorated_method_name(decorator_node: Any) -> str:
        """Find the method name that follows a NestJS decorator.

        The decorator is a sibling of the method_definition in the class body.
        """
        parent = decorator_node.parent
        if parent is None:
            return "<unknown>"

        # In tree-sitter TypeScript, decorators can be siblings of the
        # method definition, or the decorator can be inside a
        # "method_definition" node as a child.
        # Check siblings after this decorator.
        found_decorator = False
        for child in parent.children:
            if child.type == "decorator" and child == decorator_node:
                found_decorator = True
                continue
            if found_decorator and child.type == "method_definition":
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    return name_node.text.decode()
                return "<unknown>"

        # If the parent itself is a method_definition, check its name.
        if parent.type == "method_definition":
            name_node = parent.child_by_field_name("name")
            if name_node is not None:
                return name_node.text.decode()

        return "<unknown>"

    # ------------------------------------------------------------------
    # C# endpoint extraction (REQ-014)
    # ------------------------------------------------------------------

    def _extract_csharp_endpoints(
        self, root: Any, source: bytes
    ) -> list[dict[str, Any]]:
        """Extract HTTP endpoints from C# source using AST walking.

        Detects ASP.NET attribute patterns:
        - [HttpGet], [HttpGet("/path")]
        - [HttpPost], [HttpPost("/path")]
        - [HttpPut], [HttpDelete], [HttpPatch]
        - [Route("/path")]
        """
        endpoints: list[dict[str, Any]] = []
        self._walk_csharp_node(root, endpoints, source)
        return endpoints

    def _walk_csharp_node(
        self, node: Any, endpoints: list[dict[str, Any]], source: bytes
    ) -> None:
        """Recursively walk a C# AST looking for attribute-decorated methods."""
        if node.type == "attribute_list":
            self._check_csharp_attributes(node, endpoints, source)

        for child in node.children:
            self._walk_csharp_node(child, endpoints, source)

    def _check_csharp_attributes(
        self, attr_list_node: Any, endpoints: list[dict[str, Any]], source: bytes
    ) -> None:
        """Check an attribute_list node for ASP.NET route attributes.

        Only processes attributes that are inside method_declaration nodes,
        skipping class-level [Route] attributes that define base paths.
        """
        parent = attr_list_node.parent
        # Only extract endpoints from method-level attributes.
        if parent is None or parent.type not in ("method_declaration",):
            return

        for child in attr_list_node.children:
            if child.type == "attribute":
                endpoint = self._parse_csharp_attribute(child, attr_list_node, source)
                if endpoint is not None:
                    endpoints.append(endpoint)

    def _parse_csharp_attribute(
        self, attr_node: Any, attr_list_node: Any, source: bytes
    ) -> dict[str, Any] | None:
        """Parse a single C# attribute for route information.

        In the C# tree-sitter grammar, an ``attribute`` node has an
        ``identifier`` child for the name and an optional
        ``attribute_argument_list`` child for arguments.
        """
        # The attribute name is stored as a direct identifier child.
        attr_name = self._get_csharp_attribute_name(attr_node)
        if attr_name is None or attr_name not in _ASPNET_ATTRIBUTES:
            return None

        method = _ASPNET_ATTRIBUTES[attr_name]
        path = self._extract_csharp_attribute_string_arg(attr_node, source)

        # Find the method name this attribute applies to.
        handler = self._find_csharp_attributed_method(attr_list_node)

        if method is None:
            # [Route] attribute without explicit method; default to GET
            method = "GET"

        return {
            "method": method,
            "path": path,
            "handler": handler,
            "line": attr_node.start_point[0] + 1,
        }

    @staticmethod
    def _get_csharp_attribute_name(attr_node: Any) -> str | None:
        """Get the name of a C# attribute from its identifier child."""
        # Try field-based access first.
        name_node = attr_node.child_by_field_name("name")
        if name_node is not None:
            return name_node.text.decode()
        # Fall back to finding the first identifier child.
        for child in attr_node.children:
            if child.type == "identifier":
                return child.text.decode()
        return None

    @staticmethod
    def _extract_csharp_attribute_string_arg(attr_node: Any, source: bytes) -> str:
        """Extract the first string argument from a C# attribute.

        E.g., [HttpGet("/api/users")] -> "/api/users"

        In the C# tree-sitter grammar the arguments are inside an
        ``attribute_argument_list`` child, which contains
        ``attribute_argument`` children holding ``string_literal`` nodes.
        """
        # Find the attribute_argument_list child (not via field name).
        args_node = None
        for child in attr_node.children:
            if child.type == "attribute_argument_list":
                args_node = child
                break

        if args_node is None:
            return ""

        # Walk through the argument list looking for string literals.
        for child in args_node.named_children:
            if child.type == "attribute_argument":
                for sub in child.named_children:
                    if sub.type in ("string_literal", "verbatim_string_literal"):
                        raw = sub.text.decode()
                        return _strip_csharp_string(raw)
            if child.type in ("string_literal", "verbatim_string_literal"):
                raw = child.text.decode()
                return _strip_csharp_string(raw)

        return ""

    @staticmethod
    def _find_csharp_attributed_method(attr_list_node: Any) -> str:
        """Find the method name from a C# attribute_list's context.

        In the C# tree-sitter grammar, ``attribute_list`` is a child of
        ``method_declaration``.  The method_declaration has multiple
        ``identifier`` children: the return type comes first, then the
        method name (which is followed by a ``parameter_list``).

        For class-level attributes, the attribute_list is a child of the
        class_declaration.
        """
        parent = attr_list_node.parent
        if parent is None:
            return "<unknown>"

        if parent.type == "method_declaration":
            # In C# tree-sitter, the method name is the identifier that
            # immediately precedes the parameter_list.  We collect all
            # identifiers and return the last one before a parameter_list.
            last_identifier = None
            for child in parent.children:
                if child.type == "identifier":
                    last_identifier = child.text.decode()
                elif child.type == "parameter_list":
                    # The identifier just before parameter_list is the name.
                    if last_identifier is not None:
                        return last_identifier
            if last_identifier is not None:
                return last_identifier
            return "<unknown>"

        # For class-level attributes, look at the next sibling that is a
        # method_declaration.
        found_attr = False
        for child in parent.children:
            if child == attr_list_node:
                found_attr = True
                continue
            if found_attr and child.type == "method_declaration":
                last_identifier = None
                for sub in child.children:
                    if sub.type == "identifier":
                        last_identifier = sub.text.decode()
                    elif sub.type == "parameter_list":
                        if last_identifier is not None:
                            return last_identifier
                if last_identifier is not None:
                    return last_identifier
                return "<unknown>"

        return "<unknown>"

    # ------------------------------------------------------------------
    # Go endpoint extraction (REQ-014)
    # ------------------------------------------------------------------

    def _extract_go_endpoints(
        self, root: Any, source: bytes
    ) -> list[dict[str, Any]]:
        """Extract HTTP endpoints from Go source using AST walking.

        Detects patterns:
        - http.HandleFunc("/path", handler)
        - http.Handle("/path", handler)
        - mux.HandleFunc("/path", handler)
        - mux.Handle("/path", handler)
        - r.HandleFunc("/path", handler) (gorilla/mux)
        """
        endpoints: list[dict[str, Any]] = []
        self._walk_go_node(root, endpoints, source)
        return endpoints

    def _walk_go_node(
        self, node: Any, endpoints: list[dict[str, Any]], source: bytes
    ) -> None:
        """Recursively walk a Go AST looking for HTTP handler registrations."""
        if node.type == "call_expression":
            endpoint = self._check_go_http_call(node, source)
            if endpoint is not None:
                endpoints.append(endpoint)

        for child in node.children:
            self._walk_go_node(child, endpoints, source)

    def _check_go_http_call(
        self, call_node: Any, source: bytes
    ) -> dict[str, Any] | None:
        """Check if a Go call_expression is an HTTP handler registration.

        Patterns:
        - http.HandleFunc("/path", handler)
        - http.Handle("/path", handler)
        - mux.HandleFunc("/path", handler)
        - r.HandleFunc("/path", handler).Methods("GET")
        """
        func_node = call_node.child_by_field_name("function")
        if func_node is None:
            return None

        # selector_expression: http.HandleFunc or mux.Handle
        if func_node.type == "selector_expression":
            operand_node = func_node.child_by_field_name("operand")
            field_node = func_node.child_by_field_name("field")
            if operand_node is None or field_node is None:
                return None

            field_name = field_node.text.decode()
            if field_name not in ("HandleFunc", "Handle", "Get", "Post", "Put",
                                  "Delete", "Patch", "Head", "Options"):
                return None

            # Extract the path from the first argument.
            path = self._extract_go_first_string_arg(call_node, source)
            handler = self._extract_go_handler_name(call_node, source)

            # Determine method: HandleFunc/Handle are generic,
            # .Get/.Post etc. are method-specific (gorilla/mux, chi).
            method_specific = {
                "Get": "GET", "Post": "POST", "Put": "PUT",
                "Delete": "DELETE", "Patch": "PATCH",
                "Head": "HEAD", "Options": "OPTIONS",
            }

            if field_name in method_specific:
                method = method_specific[field_name]
            else:
                # HandleFunc / Handle: method is determined at runtime.
                # Check for chained .Methods("GET") call.
                method = self._extract_go_chained_method(call_node, source)
                if method is None:
                    method = "ANY"

            return {
                "method": method,
                "path": path,
                "handler": handler,
                "line": call_node.start_point[0] + 1,
            }

        return None

    @staticmethod
    def _extract_go_first_string_arg(call_node: Any, source: bytes) -> str:
        """Extract the first string literal argument from a Go call expression."""
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            return ""

        for child in args_node.named_children:
            if child.type == "interpreted_string_literal":
                raw = child.text.decode()
                # Strip surrounding double quotes.
                if raw.startswith('"') and raw.endswith('"'):
                    return raw[1:-1]
                return raw
            if child.type == "raw_string_literal":
                raw = child.text.decode()
                if raw.startswith('`') and raw.endswith('`'):
                    return raw[1:-1]
                return raw
            # Stop at the first argument if it's not a string.
            break

        return ""

    @staticmethod
    def _extract_go_handler_name(call_node: Any, source: bytes) -> str:
        """Extract the handler name from the second argument of a Go HTTP call."""
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            return "<anonymous>"

        named_children = args_node.named_children
        if len(named_children) >= 2:
            handler_arg = named_children[1]
            if handler_arg.type == "identifier":
                return handler_arg.text.decode()
            if handler_arg.type == "selector_expression":
                return handler_arg.text.decode()
            if handler_arg.type == "func_literal":
                return "<anonymous>"

        return "<anonymous>"

    @staticmethod
    def _extract_go_chained_method(call_node: Any, source: bytes) -> str | None:
        """Check for a chained .Methods("GET") call on a Go HTTP registration.

        Pattern: mux.HandleFunc("/path", handler).Methods("GET")
        """
        parent = call_node.parent
        if parent is None:
            return None

        # If the call is used as the operand of a selector_expression
        # that calls .Methods(...)
        if parent.type == "selector_expression":
            field_node = parent.child_by_field_name("field")
            if field_node is not None and field_node.text.decode() == "Methods":
                grandparent = parent.parent
                if grandparent is not None and grandparent.type == "call_expression":
                    args = grandparent.child_by_field_name("arguments")
                    if args is not None:
                        for child in args.named_children:
                            if child.type == "interpreted_string_literal":
                                raw = child.text.decode()
                                if raw.startswith('"') and raw.endswith('"'):
                                    return raw[1:-1].upper()

        return None

    # ------------------------------------------------------------------
    # Event extraction (all languages)
    # ------------------------------------------------------------------

    def _extract_events(
        self,
        root: Any,
        language: str,
        source: bytes,
        published: list[dict[str, Any]],
        consumed: list[dict[str, Any]],
    ) -> None:
        """Extract event publish/subscribe patterns from the AST."""
        if language == "python":
            self._walk_python_events(root, source, published, consumed)
        elif language == "typescript":
            self._walk_ts_events(root, source, published, consumed)
        elif language == "csharp":
            self._walk_csharp_events(root, source, published, consumed)
        elif language == "go":
            self._walk_go_events(root, source, published, consumed)

    def _walk_python_events(
        self,
        node: Any,
        source: bytes,
        published: list[dict[str, Any]],
        consumed: list[dict[str, Any]],
    ) -> None:
        """Walk Python AST for event emit/subscribe patterns."""
        if node.type == "call":
            self._check_python_event_call(node, source, published, consumed)

        for child in node.children:
            self._walk_python_events(child, source, published, consumed)

    def _check_python_event_call(
        self,
        call_node: Any,
        source: bytes,
        published: list[dict[str, Any]],
        consumed: list[dict[str, Any]],
    ) -> None:
        """Check a Python call node for event publish/subscribe patterns."""
        func_node = call_node.child_by_field_name("function")
        if func_node is None:
            return

        if func_node.type == "attribute":
            attr_node = func_node.child_by_field_name("attribute")
            if attr_node is None:
                return

            method_name = attr_node.text.decode()
            event_name = self._extract_python_first_string_arg(call_node, source)
            if not event_name:
                event_name = self._infer_event_name_from_arg(call_node, source)

            line = call_node.start_point[0] + 1

            if method_name in _PYTHON_PUBLISH_METHODS:
                channel = self._extract_event_channel(func_node, source)
                published.append({
                    "name": event_name,
                    "channel": channel,
                    "line": line,
                })
            elif method_name in _PYTHON_CONSUME_METHODS:
                channel = self._extract_event_channel(func_node, source)
                consumed.append({
                    "name": event_name,
                    "channel": channel,
                    "line": line,
                })

    def _walk_ts_events(
        self,
        node: Any,
        source: bytes,
        published: list[dict[str, Any]],
        consumed: list[dict[str, Any]],
    ) -> None:
        """Walk TypeScript AST for event emit/subscribe patterns."""
        if node.type == "call_expression":
            self._check_ts_event_call(node, source, published, consumed)

        for child in node.children:
            self._walk_ts_events(child, source, published, consumed)

    def _check_ts_event_call(
        self,
        call_node: Any,
        source: bytes,
        published: list[dict[str, Any]],
        consumed: list[dict[str, Any]],
    ) -> None:
        """Check a TypeScript call_expression for event patterns."""
        func_node = call_node.child_by_field_name("function")
        if func_node is None:
            return

        if func_node.type == "member_expression":
            prop_node = func_node.child_by_field_name("property")
            if prop_node is None:
                return

            method_name = prop_node.text.decode()
            event_name = self._extract_ts_first_string_arg(call_node, source)
            if not event_name:
                event_name = self._infer_ts_event_name(call_node, source)

            line = call_node.start_point[0] + 1

            if method_name in _TS_PUBLISH_METHODS:
                channel = self._extract_ts_event_channel(func_node, source)
                published.append({
                    "name": event_name,
                    "channel": channel,
                    "line": line,
                })
            elif method_name in _TS_CONSUME_METHODS:
                channel = self._extract_ts_event_channel(func_node, source)
                consumed.append({
                    "name": event_name,
                    "channel": channel,
                    "line": line,
                })

    def _walk_csharp_events(
        self,
        node: Any,
        source: bytes,
        published: list[dict[str, Any]],
        consumed: list[dict[str, Any]],
    ) -> None:
        """Walk C# AST for event publish/subscribe patterns.

        Detects patterns like:
        - eventBus.Publish(new UserCreated(...))
        - eventBus.Subscribe<UserCreated>(handler)
        - mediator.Send(new CreateUserCommand(...))
        """
        if node.type == "invocation_expression":
            self._check_csharp_event_invocation(node, source, published, consumed)

        for child in node.children:
            self._walk_csharp_events(child, source, published, consumed)

    def _check_csharp_event_invocation(
        self,
        invoc_node: Any,
        source: bytes,
        published: list[dict[str, Any]],
        consumed: list[dict[str, Any]],
    ) -> None:
        """Check a C# invocation_expression for event patterns."""
        func_node = None
        for child in invoc_node.children:
            if child.type == "member_access_expression":
                func_node = child
                break

        if func_node is None:
            return

        # Get the method name from the member_access_expression.
        name_node = func_node.child_by_field_name("name")
        if name_node is None:
            return

        method_name = name_node.text.decode()
        line = invoc_node.start_point[0] + 1

        publish_methods = {"Publish", "PublishAsync", "Send", "SendAsync",
                          "RaiseEvent", "Emit"}
        subscribe_methods = {"Subscribe", "SubscribeAsync", "Handle",
                            "HandleAsync", "Register"}

        if method_name in publish_methods:
            event_name = self._extract_csharp_event_name(invoc_node, source)
            published.append({
                "name": event_name,
                "channel": "",
                "line": line,
            })
        elif method_name in subscribe_methods:
            event_name = self._extract_csharp_generic_type_arg(name_node, source)
            if not event_name:
                event_name = self._extract_csharp_event_name(invoc_node, source)
            consumed.append({
                "name": event_name,
                "channel": "",
                "line": line,
            })

    @staticmethod
    def _extract_csharp_event_name(invoc_node: Any, source: bytes) -> str:
        """Extract event name from a C# invocation like Publish(new UserCreated(...))."""
        args_node = invoc_node.child_by_field_name("arguments")
        if args_node is None:
            # Look for argument_list child.
            for child in invoc_node.children:
                if child.type == "argument_list":
                    args_node = child
                    break

        if args_node is None:
            return "<unknown>"

        for child in args_node.named_children:
            if child.type == "argument":
                for sub in child.named_children:
                    if sub.type == "object_creation_expression":
                        type_node = sub.child_by_field_name("type")
                        if type_node is not None:
                            return type_node.text.decode()
            if child.type == "object_creation_expression":
                type_node = child.child_by_field_name("type")
                if type_node is not None:
                    return type_node.text.decode()

        return "<unknown>"

    @staticmethod
    def _extract_csharp_generic_type_arg(name_node: Any, source: bytes) -> str:
        """Extract a generic type argument like Subscribe<UserCreated>."""
        parent = name_node.parent
        if parent is None:
            return ""

        # Look for type_argument_list sibling.
        for child in parent.children:
            if child.type == "type_argument_list":
                for sub in child.named_children:
                    return sub.text.decode()

        return ""

    def _walk_go_events(
        self,
        node: Any,
        source: bytes,
        published: list[dict[str, Any]],
        consumed: list[dict[str, Any]],
    ) -> None:
        """Walk Go AST for event publish/subscribe patterns.

        Detects patterns like:
        - eventBus.Publish("topic", data)
        - eventBus.Subscribe("topic", handler)
        - nats.Publish("subject", data)
        """
        if node.type == "call_expression":
            self._check_go_event_call(node, source, published, consumed)

        for child in node.children:
            self._walk_go_events(child, source, published, consumed)

    def _check_go_event_call(
        self,
        call_node: Any,
        source: bytes,
        published: list[dict[str, Any]],
        consumed: list[dict[str, Any]],
    ) -> None:
        """Check a Go call_expression for event patterns."""
        func_node = call_node.child_by_field_name("function")
        if func_node is None:
            return

        if func_node.type != "selector_expression":
            return

        field_node = func_node.child_by_field_name("field")
        if field_node is None:
            return

        method_name = field_node.text.decode()
        line = call_node.start_point[0] + 1

        go_publish = {"Publish", "Emit", "Send", "ProduceMessage"}
        go_consume = {"Subscribe", "Consume", "Listen", "QueueSubscribe"}

        if method_name in go_publish:
            event_name = self._extract_go_first_string_arg(call_node, source)
            published.append({
                "name": event_name,
                "channel": event_name,
                "line": line,
            })
        elif method_name in go_consume:
            event_name = self._extract_go_first_string_arg(call_node, source)
            consumed.append({
                "name": event_name,
                "channel": event_name,
                "line": line,
            })

    # ------------------------------------------------------------------
    # Shared event helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_event_channel(func_node: Any, source: bytes) -> str:
        """Extract channel/topic name from a Python event call's object."""
        obj_node = func_node.child_by_field_name("object")
        if obj_node is not None:
            return obj_node.text.decode()
        return ""

    @staticmethod
    def _infer_event_name_from_arg(call_node: Any, source: bytes) -> str:
        """Infer event name from the first argument if it's not a string.

        Handles patterns like emit(UserCreated(...)) where the argument
        is a constructor call or class reference.
        """
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            return "<unknown>"

        for child in args_node.named_children:
            if child.type == "call":
                # Constructor-like: UserCreated(...)
                func = child.child_by_field_name("function")
                if func is not None:
                    return func.text.decode()
            if child.type == "identifier":
                return child.text.decode()
            if child.type == "keyword_argument":
                continue
            break

        return "<unknown>"

    @staticmethod
    def _infer_ts_event_name(call_node: Any, source: bytes) -> str:
        """Infer event name from TypeScript call arguments."""
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            return "<unknown>"

        for child in args_node.named_children:
            if child.type == "identifier":
                return child.text.decode()
            if child.type == "new_expression":
                constructor = child.child_by_field_name("constructor")
                if constructor is not None:
                    return constructor.text.decode()
            break

        return "<unknown>"

    @staticmethod
    def _extract_ts_event_channel(func_node: Any, source: bytes) -> str:
        """Extract channel name from a TypeScript member_expression object."""
        obj_node = func_node.child_by_field_name("object")
        if obj_node is not None:
            return obj_node.text.decode()
        return ""

    # ------------------------------------------------------------------
    # Generic utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _find_child_of_type(node: Any, type_name: str) -> Any | None:
        """Find the first child of the given type in a node's children."""
        for child in node.children:
            if child.type == type_name:
                return child
        return None


# ======================================================================
# Module-level string utilities
# ======================================================================


def _strip_python_string(raw: str) -> str:
    """Strip Python string quotes (single, double, triple-quoted)."""
    for prefix in ('"""', "'''", 'f"""', "f'''"):
        if raw.startswith(prefix) and raw.endswith(prefix[:3]):
            return raw[len(prefix):-3]
    for prefix in ('"', "'", 'f"', "f'"):
        if raw.startswith(prefix) and raw.endswith(prefix[-1]):
            return raw[len(prefix):-1]
    return raw


def _strip_js_string(raw: str) -> str:
    """Strip JavaScript string quotes (single or double)."""
    if len(raw) >= 2:
        if (raw[0] == '"' and raw[-1] == '"') or (raw[0] == "'" and raw[-1] == "'"):
            return raw[1:-1]
    return raw


def _strip_template_string(raw: str) -> str:
    """Strip JavaScript template string backticks."""
    if raw.startswith('`') and raw.endswith('`'):
        return raw[1:-1]
    return raw


def _strip_csharp_string(raw: str) -> str:
    """Strip C# string literal quotes."""
    # Verbatim string: @"..."
    if raw.startswith('@"') and raw.endswith('"'):
        return raw[2:-1]
    # Regular string: "..."
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def _extract_first_string_from_list(list_node: Any) -> str | None:
    """Extract the first string literal from a Python list node like ["GET", "POST"]."""
    if list_node.type != "list":
        return None

    for child in list_node.named_children:
        if child.type == "string":
            return _strip_python_string(child.text.decode())

    return None
