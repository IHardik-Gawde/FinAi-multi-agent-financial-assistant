import asyncio
import json
import re
from decimal import Decimal

from dotenv import load_dotenv
from langchain_ollama import ChatOllama

from livekit import agents
from livekit.agents import Agent, AgentSession, llm
from livekit.agents.llm import StopResponse
from livekit.plugins import deepgram, elevenlabs

from agents.supervisor import finance_workflow


load_dotenv("api/.env")


# --------------------------------------------------
# Local conversational speech model
# --------------------------------------------------

speech_llm = ChatOllama(
    model="qwen3:1.7b",
    temperature=0,
)


# --------------------------------------------------
# Indian number-to-words conversion
# --------------------------------------------------

ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]

TENS = [
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
]


def number_under_thousand(n: int) -> str:
    if n < 20:
        return ONES[n]

    if n < 100:
        remainder = n % 10
        return TENS[n // 10] + (" " + ONES[remainder] if remainder else "")

    remainder = n % 100

    return (
        ONES[n // 100]
        + " hundred"
        + (" " + number_under_thousand(remainder) if remainder else "")
    )


def number_to_indian_words(n: int) -> str:
    if n == 0:
        return "zero"

    if n < 0:
        return "minus " + number_to_indian_words(-n)

    if n >= 1_000_000_000:
        return str(n)

    parts = []

    for value, name in [
        (10_000_000, "crore"),
        (100_000, "lakh"),
        (1_000, "thousand"),
        (100, "hundred"),
    ]:
        if n >= value:
            count, n = divmod(n, value)
            parts.append(number_under_thousand(count) + " " + name)

    if n:
        parts.append(number_under_thousand(n))

    return " ".join(parts)


# --------------------------------------------------
# Currency handling and validation
# --------------------------------------------------

# Accept currency before the number (₹860,000 / INR 860,000)
# and after the number (860,000 INR), since research results may use either form.
CURRENCY_PATTERN = re.compile(
    r"(?:(?P<prefix_currency>₹|\$|INR\b|USD\b|Rs\.?)\s*"
    r"(?P<prefix_amount>[\d,]+(?:\.\d{1,2})?)"
    r"|(?P<suffix_amount>[\d,]+(?:\.\d{1,2})?)\s*"
    r"(?P<suffix_currency>INR\b|USD\b|Indian\s+rupees\b|rupees\b|dollars\b))",
    flags=re.IGNORECASE,
)


def _currency_amount_from_match(match) -> str:
    return (match.group("prefix_amount") or match.group("suffix_amount")).replace(
        ",", ""
    )


def _currency_label_from_match(match) -> str:
    currency = (
        match.group("prefix_currency") or match.group("suffix_currency") or ""
    ).lower()
    if currency in {"$", "usd", "dollars"}:
        return "US dollars"
    return "Indian rupees"


# Uploaded document results often store financial values as plain JSON numbers
# (for example, "grand_total": 22420) without repeating the currency symbol.
# Only known financial fields are considered; dates, IDs and quantities are ignored.
FINANCIAL_JSON_KEYS = (
    "subtotal",
    "cgst",
    "sgst",
    "igst",
    "tax_total",
    "shipping",
    "grand_total",
    "amount_paid",
    "balance_due",
    "unit_price",
    "amount",
    "total_income",
    "total_expenses",
    "net_difference",
    "total_pending_amount",
    "total_overdue_amount",
    "pending_amount",
    "paid_amount",
    "revenue",
    "expenses",
    "profit",
)
FINANCIAL_JSON_VALUE_PATTERN = re.compile(
    r"[\"'](?:"
    + "|".join(re.escape(key) for key in FINANCIAL_JSON_KEYS)
    + r""")["']\s*:\s*(-?\d[\d,]*(?:\.\d{1,2})?)""",
    flags=re.IGNORECASE,
)


def extract_currency_amounts(text: str) -> set:
    amounts = set()

    # Explicitly formatted currency values (₹1,000, INR 1,000, 1,000 rupees).
    for match in CURRENCY_PATTERN.finditer(text):
        try:
            amounts.add(Decimal(_currency_amount_from_match(match)))
        except Exception:
            continue

    # Financial values in extracted-document JSON may be unprefixed numbers.
    for match in FINANCIAL_JSON_VALUE_PATTERN.finditer(text):
        try:
            amounts.add(Decimal(match.group(1).replace(",", "")))
        except Exception:
            continue

    return amounts


def convert_currency_amounts_for_speech(text: str) -> str:
    def replace_amount(match):
        raw_amount = _currency_amount_from_match(match)

        if "." in raw_amount:
            whole, decimal = raw_amount.split(".")
            result = number_to_indian_words(int(whole))
            if int(decimal):
                result += " and " + number_to_indian_words(int(decimal)) + " paise"
        else:
            result = number_to_indian_words(int(raw_amount))

        return result + " " + _currency_label_from_match(match)

    return CURRENCY_PATTERN.sub(replace_amount, text)


def normalize_currency_for_speech(text: str) -> str:
    text = re.sub(r"₹\s*", "Indian rupees ", text)

    text = re.sub(
        r"\bINR\b\.?\s*",
        "Indian rupees ",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\bRs\.?\s*",
        "Indian rupees ",
        text,
        flags=re.IGNORECASE,
    )

    return re.sub(r"\s+", " ", text).strip()


def clean_for_speech(text: str) -> str:

    # Remove Markdown formatting.
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)

    # Remove headings and bullet markers.
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s*", "", text)

    # Remove unnecessary whitespace.
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_spoken_invoice_query(user_query: str) -> str:
    """Normalize obvious STT formatting artifacts while preserving invoice-ID structure."""
    text = user_query
    if not re.search(r"\binvoices?\b", text, flags=re.IGNORECASE):
        return text

    # Examples accepted: NS-2026-1048, N S 2026 1048,
    # N S dash 2026 dash 1048, and N S 2 0 2 6 1 0 4 8.
    id_pattern = re.compile(
        r"(?i)(\binvoice(?:\s+(?:number|no\.?|#))?\s+)"
        r"((?:[a-z]\s*){1,4})\s*(?:(?:dash|hyphen|[-])\s*)?"
        r"((?:\d\s*){4})\s*(?:(?:dash|hyphen|[-])\s*)?"
        r"((?:\d\s*){3,})"
    )

    def format_invoice_id(match):
        prefix = re.sub(r"\s+", "", match.group(2)).upper()
        year = re.sub(r"\D", "", match.group(3))
        serial = re.sub(r"\D", "", match.group(4))
        if len(year) == 4 and len(serial) >= 3:
            return f"{match.group(1)}{prefix}-{year}-{serial}"
        return match.group(0)

    text = id_pattern.sub(format_invoice_id, text)

    # Also collapse a numeric-only invoice reference when no alphabetic prefix exists.
    if not re.search(r"[A-Za-z]{1,4}-\d{4}-\d{3,}", text):
        text = re.sub(
            r"(?i)(\binvoice(?:\s+(?:number|no\.?|#))?\s+)(\d(?:[\s-]*\d){5,})",
            lambda m: m.group(1) + re.sub(r"\D", "", m.group(2)),
            text,
        )
    return text


def _is_period_comparison_query(user_query: str) -> bool:
    query = user_query.lower()
    period_terms = (
        "previous period",
        "prior period",
        "previous reporting period",
        "prior reporting period",
        "period over period",
        "period-over-period",
        "percentage change",
        "compared with the previous",
    )
    return any(term in query for term in period_terms)


def _has_period_comparison_limitation(display_response: str) -> bool:
    text = display_response.lower()
    limitation_markers = (
        "period comparison limitation",
        "previous-period financial data was not retrieved",
        "previous-period figures and percentage changes therefore cannot be established",
    )
    return any(marker in text for marker in limitation_markers)


def _extract_display_metric(display_response: str, label: str):
    pattern = rf"{re.escape(label)}\s*:\s*₹\s*([\d,]+(?:\.\d{{1,2}})?)"
    match = re.search(pattern, display_response, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _build_period_comparison_speech(display_response: str) -> str:
    """Build a factual response without asking the speech LLM to infer trends."""
    revenue = _extract_display_metric(display_response, "Total revenue")
    expenses = _extract_display_metric(display_response, "Total expenses")
    net_profit = _extract_display_metric(display_response, "Net profit")

    parts = []
    if revenue is not None:
        parts.append(f"Total revenue is ₹{revenue}.")
    if expenses is not None:
        parts.append(f"Total expenses are ₹{expenses}.")
    if net_profit is not None:
        parts.append(f"Net profit is ₹{net_profit}.")

    if not parts:
        return (
            "The available internal data does not provide separate figures "
            "for the current and previous reporting periods. I cannot calculate "
            "percentage changes or identify which metric improved or declined "
            "the most."
        )

    parts.append(
        "These are aggregate figures and are not separated by reporting period. "
        "The previous-period figures are unavailable, so I cannot calculate "
        "percentage changes or determine which metric improved or declined "
        "the most."
    )
    return " ".join(parts)


# --------------------------------------------------
# Exit command detection
# --------------------------------------------------


def is_exit_command(text: str) -> bool:
    # Normalize punctuation and common speech-to-text variations.
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    text = " ".join(text.split()).strip()

    # Match complete closing utterances, not keywords inside a new request.
    # Example: "thanks, but check the expenses" is not an exit command.
    exit_phrases = {
        "thank you",
        "thankyou",
        "thanks",
        "thanks a lot",
        "thank you so much",
        "thanks so much",
        "many thanks",
        "thank you very much",
        "thanks very much",
        "thank you that'll be all",
        "thank you that will be all",
        "thank you that's all",
        "thank you that is all",
        "thanks that'll be all",
        "thanks that will be all",
        "thanks that's all",
        "thanks that is all",
        "that'll be all",
        "that will be all",
        "that's all",
        "that is all",
        "that's everything",
        "that is everything",
        "nothing else",
        "nothing else thanks",
        "nothing else thank you",
        "i'm done",
        "im done",
        "we're done",
        "we are done",
        "we're good",
        "we are good",
        "goodbye",
        "bye",
        "have a good day",
        "have a great day",
        "okay thank you",
        "ok thank you",
        "alright thank you",
        "all right thank you",
        "okay thanks",
        "ok thanks",
        "alright thanks",
        "all right thanks",
    }

    return text in exit_phrases


# --------------------------------------------------
# Finance workflow
# --------------------------------------------------


def run_finance_workflow(user_query: str) -> str:

    response = finance_workflow.invoke(
        {
            "user_query": user_query,
            "next_agent": None,
            "finance_result": None,
            "research_result": None,
            "editor_result": None,
            "final_response": None,
        }
    )

    return response["final_response"]


async def run_finance_workflow_async(user_query: str) -> str:
    return await asyncio.to_thread(
        run_finance_workflow,
        user_query,
    )


# --------------------------------------------------
# Conversational voice response
# --------------------------------------------------


def create_voice_response(
    user_query: str,
    display_response: str,
) -> str:

    prompt = f"""
You are a professional AI finance employee speaking
directly to a colleague or client.

Your task is to explain the results of the user's query
in a natural, conversational way.

USER'S QUESTION:
{user_query}

AGENT RESULTS:
{display_response}

YOUR RESPONSE STYLE:

- Speak naturally, like a knowledgeable finance employee.
- Answer the user's actual question directly.
- Explain the important findings instead of reading the report.
- For comparisons, compare the relevant figures and explain
  what the differences mean.
- Mention the companies and reporting periods clearly.
- Connect related figures naturally.
- Use short, fluent sentences.
- Be concise but provide enough explanation to answer the question.
- Do not read headings, bullet points or numbered sections.
- Do not mention internal agents, tool calls, filenames,
  retrieval processes or implementation details.
- Do not repeat the same information.
- Do not invent missing information.
- If a comparison cannot be completed from the available evidence,
  clearly explain what is missing.
- Do not claim that a company performed better overall unless
  the available figures support that specific conclusion.

FINANCIAL ACCURACY RULES:

- Preserve the exact financial values from the agent results.
- Do not invent financial figures.
- You may calculate a difference or percentage change only when the source
  provides clearly labelled, comparable values for both periods and the same
  company or organization.
- If either period is missing, or the sources refer to different entities,
  say that a reliable comparison cannot be made. Do not infer or fill gaps.
- Do not treat an unlabeled organization-wide summary as a company-specific
  or period-specific figure.
- Preserve every source amount exactly; do not round or silently reformat it.
- When mentioning a currency amount, preserve the exact currency and numeric
  value shown in the source. Do not change currency symbols or abbreviate values.
- Do not calculate totals, differences, or percentages unless the source already
  explicitly provides that result.
- You may omit irrelevant figures to keep the response concise.

CURRENCY EXAMPLE:

Correct: Revenue was ₹860,000.
Incorrect: Revenue was ₹8,60,000 if the source says ₹860,000.
Incorrect: Revenue was eight lakh sixty thousand rupees.

Return only the conversational response.
Do not return headings or explanations about your task.
"""

    # Do not ask the speech model to interpret an explicitly incomplete
    # period comparison. Build the response deterministically from the
    # verified figures already present in the display response.
    if _is_period_comparison_query(user_query) and _has_period_comparison_limitation(
        display_response
    ):
        spoken_text = _build_period_comparison_speech(display_response)
    else:
        result = speech_llm.invoke(prompt)
        spoken_text = result.content.strip()

        # Remove Qwen thinking section if present.
        if "</think>" in spoken_text:
            spoken_text = spoken_text.split("</think>", 1)[-1].strip()

        if not spoken_text:
            raise ValueError("Qwen returned an empty speech response.")

    # Validate every spoken currency amount against the source results.
    # If Qwen abbreviates, changes currency, or invents a figure, retry once
    # with the exact validation failure instead of immediately abandoning speech.
    source_amounts = extract_currency_amounts(display_response)

    def validate_spoken_amounts(candidate: str) -> set:
        generated = extract_currency_amounts(candidate)
        if source_amounts and not generated:
            return {"missing_currency_values"}
        return generated - source_amounts

    unsupported_amounts = validate_spoken_amounts(spoken_text)

    if unsupported_amounts:
        retry_prompt = (
            prompt
            + "\\n\\nIMPORTANT CORRECTION: Your previous response contained "
            + f"unsupported or altered currency values: {sorted(map(str, unsupported_amounts))}. "
            + "Rewrite the response using only exact currency amounts explicitly "
            + "present in AGENT RESULTS. Preserve every amount digit-for-digit "
            + "and preserve its currency. Do not abbreviate thousands or lakhs. "
            + "Do not calculate or introduce totals. If a figure is unclear, omit it."
        )
        retry_result = speech_llm.invoke(retry_prompt)
        retry_text = retry_result.content.strip()
        if "</think>" in retry_text:
            retry_text = retry_text.split("</think>", 1)[-1].strip()
        if retry_text:
            retry_unsupported = validate_spoken_amounts(retry_text)
            if not retry_unsupported:
                spoken_text = retry_text
            else:
                raise ValueError(
                    "Speech model produced unsupported currency values after retry: "
                    f"{retry_unsupported}"
                )
        else:
            raise ValueError("Qwen returned an empty speech response on retry.")

    # Only after validation, convert amounts into spoken words.
    spoken_text = convert_currency_amounts_for_speech(spoken_text)

    spoken_text = clean_for_speech(spoken_text)

    spoken_text = normalize_currency_for_speech(spoken_text)

    return spoken_text


async def create_voice_response_async(
    user_query: str,
    display_response: str,
) -> str:

    return await asyncio.to_thread(
        create_voice_response,
        user_query,
        display_response,
    )


# --------------------------------------------------
# Finance Voice Agent
# --------------------------------------------------


class FinanceVoiceAgent(Agent):
    def __init__(self, room=None):

        print("[Voice Agent] Initializing FinanceVoiceAgent")
        self.room = room

        super().__init__(
            instructions=("You are the voice interface for an AI Finance Employee.")
        )

    async def publish_ui_event(self, event_type: str, **data):
        """Send a small JSON event to the connected React participant."""
        if self.room is None:
            return

        try:
            payload = json.dumps({"type": event_type, **data}).encode("utf-8")
            await self.room.local_participant.publish_data(
                payload,
                reliable=True,
                topic="finance-assistant",
            )
        except Exception as error:
            # UI updates must never interrupt the finance workflow or speech.
            print(f"[Voice Agent] UI event publish failed ({event_type}): {error}")

    async def on_user_turn_completed(
        self,
        turn_ctx: llm.ChatContext,
        new_message: llm.ChatMessage,
    ) -> None:

        print("[Voice Agent] User turn completed!")

        user_query = new_message.text_content
        if user_query:
            normalized_query = normalize_spoken_invoice_query(user_query)
            if normalized_query != user_query:
                print(
                    f"[Voice Agent] Normalized invoice transcript: {normalized_query}"
                )
                user_query = normalized_query

        if not user_query:
            raise StopResponse()

        print(f"[Voice Agent] Query: {user_query}")
        # Interim/final transcript updates are streamed by the session event
        # handler registered in entrypoint. This callback starts the workflow.
        await self.publish_ui_event("status", status="thinking")

        # Handle conversation-ending commands.
        if is_exit_command(user_query):
            print("[Voice Agent] Closing conversation...")
            await self.publish_ui_event("status", status="speaking")

            await self.session.say(
                "You're welcome. It was a pleasure helping you. Have a great day!",
                allow_interruptions=False,
            )

            await self.publish_ui_event("ended")
            self.session.shutdown(drain=True)

            print("[Voice Agent] Session shutdown requested.")

            raise StopResponse()

        # 1. Execute the existing finance workflow.
        display_response = await run_finance_workflow_async(user_query)

        # Preserve the original display response.
        print("\n========== DISPLAY RESPONSE ==========")
        print(display_response)
        await self.publish_ui_event("display_response", text=display_response)

        # 2. Generate a conversational explanation.
        try:
            spoken_response = await create_voice_response_async(
                user_query,
                display_response,
            )

        except Exception as error:
            print(f"[Voice Agent] Voice formatting error: {error}")

            print("[Voice Agent] Using safe speech fallback.")

            # Never read the raw workflow report aloud. It contains internal
            # section headings and specialist output intended for the UI.
            spoken_response = (
                "I retrieved the available results, but I could not safely prepare the spoken summary. "
                "Please refer to the financial results shown on screen."
            )

        print("\n========== VOICE RESPONSE ==========")
        print(spoken_response)

        # Keep the spoken explanation separate from the original finance output.
        await self.publish_ui_event("voice_response", text=spoken_response)

        # 3. Speak the conversational explanation.
        await self.publish_ui_event("status", status="speaking")
        await self.session.say(spoken_response)
        await self.publish_ui_event("status", status="listening")

        raise StopResponse()


# --------------------------------------------------
# LiveKit entrypoint
# --------------------------------------------------


async def entrypoint(ctx: agents.JobContext):

    session = AgentSession(
        turn_handling={
            "endpointing": {
                "mode": "fixed",
                "min_delay": 2.0,
                "max_delay": 5.0,
            }
        },
        stt=deepgram.STT(
            model="nova-3",
            language="en",
            interim_results=True,
            numerals=True,
        ),
        tts=elevenlabs.TTS(
            voice_settings=elevenlabs.VoiceSettings(
                stability=0.4,
                similarity_boost=0.75,
                style=0.5,
                use_speaker_boost=True,
            )
        ),
    )

    agent = FinanceVoiceAgent(ctx.room)

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(event):
        transcript = getattr(event, "transcript", "") or ""
        if not transcript.strip():
            return

        is_final = bool(getattr(event, "is_final", False))
        asyncio.create_task(
            agent.publish_ui_event(
                "transcript",
                text=transcript,
                is_final=is_final,
            )
        )

    async def process_text_query(request_id: str, user_query: str):
        query = normalize_spoken_invoice_query((user_query or "").strip())
        if not query:
            await agent.publish_ui_event(
                "text_error", request_id=request_id, text="Please enter a question."
            )
            return

        print(f"[Voice Agent] Text query: {query}")
        await agent.publish_ui_event("status", status="thinking")
        try:
            display_response = await run_finance_workflow_async(query)
            try:
                assistant_response = await create_voice_response_async(
                    query, display_response
                )
            except Exception as error:
                print(f"[Voice Agent] Text response formatting error: {error}")
                assistant_response = (
                    "I retrieved the available financial information, but I cannot "
                    "make a reliable comparison where the required reporting-period "
                    "data is missing. The supporting details are available below."
                )

            await agent.publish_ui_event(
                "text_response",
                request_id=request_id,
                text=assistant_response,
                details=display_response,
            )
        except Exception as error:
            print(f"[Voice Agent] Text query failed: {error}")
            await agent.publish_ui_event(
                "text_error",
                request_id=request_id,
                text="I couldn't complete that request. Please try again.",
            )
        finally:
            await agent.publish_ui_event("status", status="ready")

    @ctx.room.on("data_received")
    def on_data_received(packet):
        if getattr(packet, "topic", None) != "finance-assistant-input":
            return
        try:
            message = json.loads(packet.data.decode("utf-8"))
            if message.get("type") != "text_query":
                return
            request_id = str(message.get("request_id", ""))
            user_query = str(message.get("text", ""))
            if not request_id:
                return
            asyncio.create_task(process_text_query(request_id, user_query))
        except Exception as error:
            print(f"[Voice Agent] Invalid text message received: {error}")

    await session.start(
        room=ctx.room,
        agent=agent,
    )

    await ctx.connect()
    await agent.publish_ui_event("agent_ready")


# --------------------------------------------------
# Application entrypoint
# --------------------------------------------------

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
