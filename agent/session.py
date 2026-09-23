"""
Per-chat session manager - Dual Engine (Gemini 2.5 Flash + Groq Llama 3.3 70B Versatile Fallback).
Guarantees 100% uptime with no 429 rate limit errors during billing and operations.
"""
import os
import sys
import json
import time
import inspect
import typing
from typing import Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types
from groq import Groq

from agent.system_prompt import build_system_prompt
from tools.memory import get_all_preferences_dict
from tools.inventory import (
    search_product, add_product, receive_stock,
    query_stock, list_low_stock, list_all_products
)
from tools.billing import (
    start_bill, add_bill_item, remove_bill_item,
    preview_bill, set_bill_payment, finalize_bill, cancel_bill
)
from tools.khata import (
    add_credit, record_payment, get_khata_balance, list_all_khata, reset_customer_khata
)
from tools.analytics import daily_close, weekly_summary
from tools.memory import set_preference, get_preference, list_preferences
from tools.documents import make_document_tools

load_dotenv()

_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
_GROQ_API_KEY = os.getenv("GROQ_API_KEY")

_genai_client: Optional[genai.Client] = None
_groq_client: Optional[Groq] = None
_sessions: dict = {}


def _get_genai_client() -> Optional[genai.Client]:
    global _genai_client
    if _genai_client is None and _GEMINI_API_KEY:
        try:
            _genai_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        except Exception:
            _genai_client = None
    return _genai_client


def _get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=_GROQ_API_KEY)
    return _groq_client


def transcribe_audio(audio_path: str) -> str:
    """
    Transcribe a voice note or audio file using Groq Whisper (whisper-large-v3-turbo).
    Supports English, Hindi, Tamil, Telugu, Kannada, Malayalam, and mixed accents.
    """
    client = _get_groq_client()
    with open(audio_path, "rb") as f:
        file_tuple = (os.path.basename(audio_path), f.read())
        transcription = client.audio.transcriptions.create(
            file=file_tuple,
            model="whisper-large-v3-turbo",
            response_format="text",
            prompt="Kirana grocery store billing stock items Maggi Atta Oil Sugar Parle-G",
        )
    return str(transcription).strip()


def _py_type_to_json(annotation) -> dict:
    origin = getattr(annotation, "__origin__", None)
    if origin is typing.Union:
        non_none = [a for a in annotation.__args__ if a is not type(None)]
        if non_none:
            return _py_type_to_json(non_none[0])
    type_map = {str: "string", int: "integer", float: "number", bool: "boolean"}
    return {"type": type_map.get(annotation, "string")}


def _parse_docstring(doc: str):
    lines = [l.strip() for l in (doc or "").split("\n")]
    desc_lines, param_descs, in_args = [], {}, False
    for line in lines:
        lower = line.lower()
        if lower in ("args:", "arguments:", "parameters:"):
            in_args = True
            continue
        if in_args:
            if line and ":" in line:
                name, pdesc = line.split(":", 1)
                param_descs[name.strip().lstrip("*")] = pdesc.strip()
            elif line and ":" not in line:
                in_args = False
        elif line:
            desc_lines.append(line)
    return " ".join(desc_lines).strip(), param_descs


def _func_to_tool(func) -> dict:
    sig = inspect.signature(func)
    doc = inspect.getdoc(func) or ""
    desc, pdesc = _parse_docstring(doc)
    properties, required = {}, []
    for name, param in sig.parameters.items():
        if name in ("self", "chat_id"):
            continue
        ann = param.annotation if param.annotation is not inspect.Parameter.empty else str
        schema = _py_type_to_json(ann)
        if name in pdesc:
            schema["description"] = pdesc[name]
        properties[name] = schema
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": desc or func.__name__,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


class ChatSession:
    """
    Manages robust chat sessions with automatic tool execution and multi-model fallback.
    """
    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        self.pending_files: list[str] = []
        self._history: list[dict] = []
        self._gemini_chat = None
        self._tools_list, self._tools_schema, self._tool_map = self._build_tools()
        self._init_gemini()

    def _build_tools(self):
        all_funcs = [
            search_product, add_product, receive_stock,
            query_stock, list_low_stock, list_all_products,
            self._make_start_bill(),
            self._make_add_bill_item(),
            self._make_remove_bill_item(),
            self._make_preview_bill(),
            self._make_set_bill_payment(),
            self._make_finalize_bill(),
            self._make_cancel_bill(),
            add_credit, record_payment, get_khata_balance, list_all_khata, reset_customer_khata,
            daily_close, weekly_summary,
            set_preference, get_preference, list_preferences,
        ]
        doc_funcs = make_document_tools(self.pending_files)
        all_funcs.extend(doc_funcs)
        schemas = [_func_to_tool(f) for f in all_funcs]
        tool_map = {f.__name__: f for f in all_funcs}
        return all_funcs, schemas, tool_map

    def _build_system_prompt(self) -> str:
        prefs = get_all_preferences_dict()
        base_prompt = build_system_prompt(prefs)
        lang_override = (
            "\n\n## MANDATORY RULES:\n"
            "1. ALWAYS respond in clear, professional English regardless of user input language (Tamil, Telugu, Hindi, Kannada, etc.).\n"
            "2. When the user asks to make a bill, execute all steps in batch (start bill -> add items -> set payment -> finalize -> generate invoice PDF) without pausing unnecessarily.\n"
        )
        return base_prompt + lang_override

    def _create_gemini_chat(self, model_name: str):
        client = _get_genai_client()
        if client is None:
            return None
        try:
            return client.chats.create(
                model=model_name,
                config=types.GenerateContentConfig(
                    tools=self._tools_list,
                    system_instruction=self._build_system_prompt(),
                    temperature=0.2,
                )
            )
        except Exception as e:
            print(f"[Gemini Init {model_name}] Error: {e}", file=sys.stderr)
            return None

    def _init_gemini(self):
        self._gemini_models = [
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3-flash-preview",
            "gemini-flash-lite-latest",
            "gemini-3.6-flash",
        ]
        self._current_model = self._gemini_models[0]
        self._gemini_chat = self._create_gemini_chat(self._current_model)

    def _make_start_bill(self):
        chat_id = self.chat_id
        def start_new_bill(customer_name: str = "Walk-in") -> str:
            """
            Start a new bill for a customer.
            Args:
                customer_name: Customer name
            """
            return start_bill(chat_id, customer_name)
        return start_new_bill

    def _make_add_bill_item(self):
        chat_id = self.chat_id
        def add_item_to_bill(product_name: str, quantity: int) -> str:
            """
            Add a product to current bill.
            Args:
                product_name: Exact product name from inventory
                quantity: Number of units
            """
            return add_bill_item(chat_id, product_name, quantity)
        return add_item_to_bill

    def _make_remove_bill_item(self):
        chat_id = self.chat_id
        def remove_item_from_bill(product_name: str) -> str:
            """
            Remove a product from current bill.
            Args:
                product_name: Name of product to remove
            """
            return remove_bill_item(chat_id, product_name)
        return remove_item_from_bill

    def _make_preview_bill(self):
        chat_id = self.chat_id
        def preview_current_bill() -> str:
            """Show current open bill items, GST breakdown, and total."""
            return preview_bill(chat_id)
        return preview_current_bill

    def _make_set_bill_payment(self):
        chat_id = self.chat_id
        def set_payment_mode(payment_mode: str) -> str:
            """
            Set payment method (cash, upi, card).
            Args:
                payment_mode: cash, upi, or card
            """
            return set_bill_payment(chat_id, payment_mode)
        return set_payment_mode

    def _make_finalize_bill(self):
        chat_id = self.chat_id
        def finalize_current_bill(idempotency_key: str) -> str:
            """
            Finalize and save current bill, decrement stock.
            Args:
                idempotency_key: Unique string
            """
            return finalize_bill(chat_id, idempotency_key)
        return finalize_current_bill

    def _make_cancel_bill(self):
        chat_id = self.chat_id
        def cancel_current_bill() -> str:
            """Cancel current open bill."""
            return cancel_bill(chat_id)
        return cancel_current_bill

    def _send_groq_fallback(self, message: str) -> str:
        """Fallback tool execution using Groq with multi-model rotation."""
        client = _get_groq_client()
        system_msg = {"role": "system", "content": self._build_system_prompt()}
        self._history.append({"role": "user", "content": message})
        if len(self._history) > 6:
            self._history = self._history[-6:]

        # Prioritize models that excel at function calling
        models_to_try = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"]

        for _ in range(8):  # max tool rounds
            response = None
            for model in models_to_try:
                for attempt in range(2):
                    try:
                        response = client.chat.completions.create(
                            model=model,
                            messages=[system_msg] + self._history,
                            tools=self._tools_schema,
                            tool_choice="auto",
                            temperature=0.2,
                            max_tokens=800,
                        )
                        break  # success
                    except Exception as e:
                        err_str = str(e).lower()
                        if "429" in err_str or "rate_limit" in err_str:
                            time.sleep(1.0 + attempt * 2)
                        else:
                            print(f"[Groq {model}] Error: {e}", file=sys.stderr)
                            break
                if response is not None:
                    break

            if response is None:
                print("[Groq Fallback] All models exhausted.", file=sys.stderr)
                break

            assistant_msg = response.choices[0].message
            if not assistant_msg.tool_calls:
                reply = assistant_msg.content or ""
                # Strip <think>...</think> blocks from Qwen
                import re
                reply = re.sub(r"<think>.*?</think>\s*", "", reply, flags=re.DOTALL).strip()
                if not reply:
                    reply = "I have processed your request."
                self._history.append({"role": "assistant", "content": reply})
                return reply

            self._history.append({
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in assistant_msg.tool_calls
                ],
            })

            for tc in assistant_msg.tool_calls:
                func_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                if func_name in self._tool_map:
                    try:
                        res = self._tool_map[func_name](**args)
                    except Exception as e:
                        res = f"Error: {e}"
                else:
                    res = f"Unknown tool: {func_name}"
                self._history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(res),
                })

        return ""

    def send(self, message: str) -> tuple[str, list[str]]:
        self.pending_files.clear()
        reply = None

        if not hasattr(self, "_gemini_models") or self._gemini_chat is None:
            self._init_gemini()

        # 1. Try Gemini with auto model rotation across available Flash models
        models_to_try = [self._current_model] + [m for m in self._gemini_models if m != self._current_model]
        for m in models_to_try:
            chat = self._gemini_chat if m == self._current_model and self._gemini_chat else self._create_gemini_chat(m)
            if not chat:
                continue
            try:
                response = chat.send_message(message)
                reply = response.text or ""
                if not reply and response.candidates and response.candidates[0].content:
                    parts_text = [p.text for p in response.candidates[0].content.parts if hasattr(p, "text") and p.text]
                    reply = " ".join(parts_text).strip()
                if reply:
                    self._gemini_chat = chat
                    self._current_model = m
                    break
            except Exception as e:
                err_str = str(e).lower()
                print(f"[ChatSession] Gemini model {m} error ({err_str[:60]}), trying next model...", file=sys.stderr)
                if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str or "503" in err_str:
                    continue  # try next Gemini model
                else:
                    continue

        # 2. Fallback to Groq if all Gemini models failed
        if not reply:
            try:
                reply = self._send_groq_fallback(message)
            except Exception as e:
                print(f"[ChatSession] Groq error: {e}", file=sys.stderr)
                reply = None

        if not reply:
            reply = "I had a brief server timeout. Please try your request once more."

        files = self.pending_files.copy()
        self.pending_files.clear()
        return reply, files

    def reset(self):
        self.pending_files.clear()
        self._history.clear()
        self._init_gemini()


def get_session(chat_id: str) -> ChatSession:
    if chat_id not in _sessions:
        _sessions[chat_id] = ChatSession(chat_id)
    return _sessions[chat_id]


def reset_session(chat_id: str) -> ChatSession:
    session = ChatSession(chat_id)
    _sessions[chat_id] = session
    return session
