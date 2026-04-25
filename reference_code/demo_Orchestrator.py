import os
import asyncio
import sys
import pdfplumber
import docx
import json
import time
import random
import re
import ast
import requests
import httpx
from bs4 import BeautifulSoup
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI

import agentscope
from agentscope.agent import ReActAgent, UserAgent
from agentscope.message import Msg
from agentscope.tool import Toolkit, ToolResponse
from agentscope.model import OpenAIChatModel
from agentscope.formatter import OpenAIChatFormatter
from agentscope.memory import InMemoryMemory

# ==========================================
# 1. Initialization & model configuration
# ==========================================
agentscope.init()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Default to Gemini 2.5 Flash via OpenAI-compatible endpoint.
# The API key MUST be supplied via the OPENAI_API_KEY environment variable.
#   export OPENAI_API_KEY="your-gemini-api-key"
# Optional overrides: OPENAI_MODEL, OPENAI_BASE_URL, USE_CLOUD_API.
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

USE_CLOUD_API = os.getenv("USE_CLOUD_API", "true").lower() == "true"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", DEFAULT_GEMINI_MODEL)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", DEFAULT_GEMINI_BASE_URL)


def normalize_openai_model(raw_model: str | None) -> str:
    if not raw_model:
        return DEFAULT_GEMINI_MODEL
    normalized = raw_model.strip().strip("\"'")
    invalid_values = {
        "", "none", "null",
        "os.getenv(\"OPENAI_MODEL\", \"gpt-4o-mini\")",
        "os.getenv('OPENAI_MODEL', 'gpt-4o-mini')",
        "os.getenv(\"OPENAI_MODEL\")",
        "os.getenv('OPENAI_MODEL')",
    }
    if normalized.lower() in invalid_values:
        return DEFAULT_GEMINI_MODEL
    return normalized


def normalize_openai_base_url(raw_base_url: str | None) -> str | None:
    if not raw_base_url:
        return None
    normalized = raw_base_url.strip().strip("\"'")
    invalid_values = {
        "", "none", "null",
        "os.getenv(\"OPENAI_BASE_URL\")",
        "os.getenv('OPENAI_BASE_URL')",
    }
    if normalized.lower() in invalid_values:
        return None
    if not normalized.startswith(("http://", "https://")):
        return None
    return normalized


def collect_runtime_diagnostics() -> str:
    proxy_keys = [
        "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
        "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy",
    ]
    proxy_parts = [f"{k}={os.getenv(k)}" for k in proxy_keys if os.getenv(k)]
    proxy_text = ", ".join(proxy_parts) if proxy_parts else "None"
    return (
        f"python={sys.executable}\n"
        f"MODEL={normalize_openai_model(OPENAI_MODEL)}\n"
        f"BASE_URL={normalize_openai_base_url(OPENAI_BASE_URL) or 'https://api.openai.com/v1'}\n"
        f"proxy={proxy_text}"
    )


def build_openai_client_kwargs(async_client: bool = False) -> dict:
    client_kwargs = {"timeout": 60}
    if async_client:
        client_kwargs["http_client"] = httpx.AsyncClient(trust_env=False, timeout=60)
    else:
        client_kwargs["http_client"] = httpx.Client(trust_env=False, timeout=60)
    normalized_base_url = normalize_openai_base_url(OPENAI_BASE_URL)
    if normalized_base_url:
        client_kwargs["base_url"] = normalized_base_url
    return client_kwargs


def validate_openai_configuration(client_kwargs: dict) -> None:
    """Soft validation: hard-fail only on auth errors; warn on others (Gemini
    endpoint may not fully support /models listing)."""
    try:
        client = OpenAI(api_key=OPENAI_API_KEY, **client_kwargs)
        client.models.list()
    except AuthenticationError as exc:
        raise EnvironmentError(
            "API key 无效（401）。请检查 OPENAI_API_KEY（当前使用 Gemini OpenAI 兼容端点需要 Gemini API key）。"
        ) from exc
    except (APIConnectionError, APIStatusError) as exc:
        # Gemini 的 OpenAI 兼容层在部分账号下 /models 不通，属正常。跳过硬失败。
        print(f"[System Warning] Pre-flight check skipped: {exc}")
        print(collect_runtime_diagnostics())


def create_main_model():
    if USE_CLOUD_API:
        if not OPENAI_API_KEY:
            raise EnvironmentError("OPENAI_API_KEY is not set.")
        validate_openai_configuration(build_openai_client_kwargs(async_client=False))
        model = OpenAIChatModel(
            model_name=normalize_openai_model(OPENAI_MODEL),
            api_key=OPENAI_API_KEY,
            client_kwargs=build_openai_client_kwargs(async_client=True),
        )
        print(f"[System: Running on Cloud API | model={normalize_openai_model(OPENAI_MODEL)} | base_url={normalize_openai_base_url(OPENAI_BASE_URL)}]")
        return model

    model = OpenAIChatModel(
        model_name="qwen3.5:4b",
        api_key="EMPTY",
        client_kwargs={"base_url": "http://localhost:11434/v1", "timeout": 60},
    )
    print("[System: Running on Local Ollama Model]")
    return model


main_model = None
formatter = OpenAIChatFormatter()

# ==========================================
# 2. Resume parsing
# ==========================================
def parse_resume_file(file_path: str) -> str:
    if not os.path.exists(file_path):
        return "Error: File not found. Please check the path."
    ext = file_path.lower().split('.')[-1]
    text = ""
    try:
        if ext == 'pdf':
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"
        elif ext in ['doc', 'docx']:
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
    except Exception as e:
        return f"Error parsing file: {str(e)}"
    return "\n".join([line for line in text.split('\n') if line.strip() != ''])

# ==========================================
# 3. LinkedIn scraping tool
# ==========================================
def get_job_description(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        time.sleep(random.uniform(1.0, 2.0))
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            desc_elem = soup.find('div', class_='show-more-less-html__markup')
            if not desc_elem:
                desc_elem = soup.find('div', class_='description__text')
            if desc_elem:
                text = desc_elem.get_text(separator=' ', strip=True)
                return text[:1500] + "..." if len(text) > 1500 else text
        return "Detailed description unavailable (Blocked or missing)."
    except Exception as e:
        return f"Error fetching details: {str(e)}"


def fetch_linkedin_jobs(keywords_list: list, location: str = "Singapore") -> ToolResponse:
    """Search for jobs on LinkedIn using multiple keywords."""
    if isinstance(keywords_list, str):
        try:
            keywords_list = ast.literal_eval(keywords_list)
        except Exception:
            keywords_list = [keywords_list]
    if not isinstance(keywords_list, list):
        return ToolResponse(content="Error: keywords_list must be a list of strings.")

    all_results = []
    search_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for keyword in keywords_list[:3]:
        clean_keyword = str(keyword).replace('\n', ' ').strip()
        print(f"\n[System Debug] Searching LinkedIn for: '{clean_keyword}'...")
        time.sleep(random.uniform(2.0, 4.0))
        params = {"keywords": clean_keyword, "location": location, "f_TPR": "r2592000", "pageNum": 0}
        try:
            response = requests.get(search_url, params=params, headers=headers, timeout=15)
            if response.status_code != 200:
                all_results.append(f"Search for '{clean_keyword}' failed (Status {response.status_code}).")
                continue
            soup = BeautifulSoup(response.text, 'html.parser')
            job_cards = soup.find_all('li')
            if not job_cards:
                all_results.append(f"No matching jobs found on LinkedIn for '{clean_keyword}'.")
                continue
            results = []
            for card in job_cards[:3]:
                title_elem = card.find('h3', class_='base-search-card__title')
                company_elem = card.find('h4', class_='base-search-card__subtitle')
                link_elem = card.find('a', class_='base-card__full-link')
                if not link_elem:
                    continue
                raw_link = link_elem['href'].split('?')[0]
                clean_link = raw_link.strip().rstrip('\n- ')
                description = get_job_description(clean_link)
                title = title_elem.text.strip() if title_elem else "Unknown"
                company = company_elem.text.strip() if company_elem else "Unknown"
                results.append(
                    f"### Job: {title} @ {company}\n"
                    f"**Link**: {clean_link}\n"
                    f"**Requirements**: {description}\n"
                )
            if results:
                all_results.append(f"--- Results for '{clean_keyword}' ---\n" + "\n".join(results))
        except Exception as e:
            all_results.append(f"Error for '{clean_keyword}': {str(e)}")

    return ToolResponse(content="\n\n".join(all_results))


toolkit = Toolkit()
toolkit.register_tool_function(fetch_linkedin_jobs)

# ==========================================
# 4. Agents
# ==========================================
def create_agents(model):
    job_search = ReActAgent(
        name="JobSearch",
        sys_prompt=(
            "You are a Job Search Specialist for the Singapore market.\n"
            "STRICT EXECUTION RULES:\n"
            "1. Analyze the user's resume and extract core technical skills.\n"
            "2. Identify 3 DISTINCT, concise search keywords (e.g., 'Data Science', 'Backend Engineer'). DO NOT use long descriptive phrases.\n"
            "3. TOOL CALL: You MUST call `fetch_linkedin_jobs` EXACTLY ONCE, passing all 3 keywords as a list to the `keywords_list` argument.\n"
            "4. AFTER TOOL CALL: Once you receive the search results from the tool, DO NOT call the tool again under ANY circumstances.\n"
            "5. PARSING: Directly parse the returned text and format it into JSON.\n"
            "6. FINAL OUTPUT: You MUST return a pure JSON list of objects. Each object must contain:\n"
            "   - 'job_title': The official title.\n"
            "   - 'company': The company name.\n"
            "   - 'job_requirements': The detailed requirements or description fetched directly from LinkedIn.\n"
            "DO NOT output any thinking process or markdown tables in your final response. ONLY output valid JSON."
        ),
        model=model, formatter=formatter, memory=InMemoryMemory(), toolkit=toolkit,
    )

    job_post = ReActAgent(
        name="JobPost",
        sys_prompt=(
            "You are a Senior Career Advisor.\n"
            "STRICT EXECUTION RULES:\n"
            "1. You will be provided with a JSON list of LinkedIn job postings and the user's resume background.\n"
            "2. Evaluate how well the user's specific skills align with each job's requirements.\n"
            "3. Rank the jobs based on the highest relevance to the user's background.\n"
            "4. FINAL OUTPUT: You MUST return a pure JSON list of objects. Each object must contain:\n"
            "   - 'job_title': The official title.\n"
            "   - 'company': The company name.\n"
            "   - 'recommendation_reason': A customized explanation connecting the job requirements to the user's specific background.\n"
            "DO NOT output any thinking process or markdown tables. ONLY output valid JSON."
        ),
        model=model, formatter=formatter, memory=InMemoryMemory(),
    )

    resume_tailor = ReActAgent(
        name="ResumeTailor",
        sys_prompt=(
            "You are a Resume Optimisation Assistant. "
            "You will be given the user's resume plus the latest ranked jobs context. "
            "Identify the target job from the user's request, compare the user's skills against that job, "
            "then suggest edits and highlight missing keywords. Be practical and specific."
        ),
        model=model, formatter=formatter, memory=InMemoryMemory(),
    )

    interview_prep = ReActAgent(
        name="InterviewPrep",
        sys_prompt=(
            "You are an Interview Preparation Assistant. "
            "You will be given the user's resume plus the latest ranked jobs context. "
            "Identify the target role from the user's request, then generate a personalised list of 3-5 likely interview questions. "
            "Also provide a brief STAR-based answer template for one behavioral question."
        ),
        model=model, formatter=formatter, memory=InMemoryMemory(),
    )

    orchestrator = ReActAgent(
        name="Orchestrator",
        sys_prompt=(
            "You are the central Orchestrator of an AI Job Search Companion for NUS graduates entering the Singapore job market.\n"
            "You do NOT perform any domain task yourself. Your sole responsibility is intent recognition and task routing.\n\n"

            "SYSTEM CONTEXT:\n"
            "You coordinate three specialist agents in a hub-and-spoke architecture:\n"
            "  - JobMatcher: searches LinkedIn for jobs matching the user's resume, returns ranked recommendations.\n"
            "  - ResumeTailor: compares the user's resume against a target job, identifies skill gaps, and suggests optimisations.\n"
            "  - InterviewPrep: generates personalised interview questions and STAR-method answer templates.\n"
            "The typical user journey flows: job_search → resume_tailor → interview_prep, but users may jump to any stage.\n\n"

            "ROUTING RULES:\n"
            "1. Analyse the user's message together with the provided context (workflow_stage, selected_job, last_agent_output).\n"
            "2. Classify the intent into exactly ONE category:\n"
            "   - job_search: user wants to find, search, discover, browse, or explore new job opportunities.\n"
            "   - resume_tailor: user wants to edit, tailor, optimise, improve, rewrite, or review their resume/CV for a role.\n"
            "   - interview_prep: user wants to prepare for interviews, get likely questions, practice answers, or build STAR stories.\n"
            "   - general: greetings, thank-you, unclear requests, or off-topic messages.\n"
            "3. AMBIGUITY RESOLUTION — use workflow_stage and selected_job to disambiguate:\n"
            "   - If workflow_stage is 'discovery' and user says 'help me with this one' → resume_tailor.\n"
            "   - If workflow_stage is 'tailoring' and user says 'what's next' or 'help me prepare' → interview_prep.\n"
            "   - If a selected_job exists and user says 'I want to apply' or 'how do I improve my chances' → resume_tailor.\n"
            "   - If no selected_job and user's request is vague → job_search.\n"
            "   - If user mentions a specific company or role name without other context → job_search.\n\n"

            "OUTPUT FORMAT — return ONLY a single-line JSON object, no explanation, no markdown:\n"
            '{"route": "job_search"}\n\n'

            "EXAMPLES:\n"
            'User: "Search for data science positions in Singapore" → {"route": "job_search"}\n'
            'User: "Any backend engineer openings at Grab?" → {"route": "job_search"}\n'
            'User: "Can you tailor my resume for the DBS role?" → {"route": "resume_tailor"}\n'
            'User: "What keywords am I missing for this job?" → {"route": "resume_tailor"}\n'
            'User: "Help me prepare for the interview" → {"route": "interview_prep"}\n'
            'User: "What behavioural questions might they ask?" → {"route": "interview_prep"}\n'
            'User: "Thanks!" → {"route": "general"}\n'
            'User: "Hello, I just graduated from NUS" → {"route": "general"}\n'
            '[workflow_stage=discovery] User: "This one looks good, help me with it" → {"route": "resume_tailor"}\n'
            '[workflow_stage=tailoring] User: "OK what should I do next?" → {"route": "interview_prep"}\n'
        ),
        model=model, formatter=formatter, memory=InMemoryMemory(),
    )

    return job_search, job_post, resume_tailor, interview_prep, orchestrator


user_agent = UserAgent(name="User")

# ==========================================
# 5. Helpers
# ==========================================
def print_final_reply(response):
    raw_content = response.content
    if isinstance(raw_content, list):
        final_text = "".join([item.get("text", "") for item in raw_content if item.get("type") == "text"])
    else:
        final_text = str(raw_content)
    try:
        json_str = final_text.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()
        data = json.loads(json_str)
        print(f"\n[{response.name} (JSON Output)]:")
        print(json.dumps(data, indent=4, ensure_ascii=False))
    except Exception:
        print(f"\n[{response.name}]: {final_text}")


def build_context_message(user_resume_text: str, latest_ranked_jobs_json: str, user_request: str, selected_job: str | None = None) -> Msg:
    parts = [f"User's Resume Background:\n{user_resume_text}"]
    if latest_ranked_jobs_json:
        parts.append(f"Latest Ranked Jobs (JSON):\n{latest_ranked_jobs_json}")
    if selected_job:
        parts.append(f"Target Job: {selected_job}")
    parts.append(f"User's Request:\n{user_request}")
    return Msg(name="System", content="\n\n".join(parts), role="user")


def parse_routing_decision(response) -> str:
    raw = response.content
    if isinstance(raw, list):
        raw = "".join([item.get("text", "") for item in raw if item.get("type") == "text"])
    raw = str(raw)
    try:
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        data = json.loads(text)
        route = data.get("route", "").lower().strip()
        if route in ("job_search", "resume_tailor", "interview_prep", "general"):
            return route
    except (json.JSONDecodeError, AttributeError, IndexError):
        pass
    match = re.search(r'"route"\s*:\s*"(\w+)"', raw)
    if match:
        route = match.group(1).lower()
        if route in ("job_search", "resume_tailor", "interview_prep", "general"):
            return route
    return ""


def keyword_fallback(content_lower: str) -> str:
    if any(kw in content_lower for kw in ("tailor", "resume", "edit", "optimis", "improve")):
        return "resume_tailor"
    elif any(kw in content_lower for kw in ("interview", "prepare", "question", "star")):
        return "interview_prep"
    else:
        return "job_search"


# ==========================================
# 6. Multi-turn workflow (Orchestrator-driven)
# ==========================================
async def main():
    global main_model
    if main_model is None:
        main_model = create_main_model()
    (job_search_agent, job_post_agent, resume_tailor_agent,
     interview_prep_agent, orchestrator_agent) = create_agents(main_model)

    print("Welcome to the AI Job Search Companion!")
    print("---------------------------------------------------")

    resume_path = input("Please enter the path to your resume (PDF/DOCX/TXT) or drag file here:\n> ").strip()
    resume_path = resume_path.strip('"\'')

    print("\n[System: Parsing document...]")
    user_resume_text = parse_resume_file(resume_path)
    if user_resume_text.startswith("Error"):
        print(f"\n[System Error]: {user_resume_text}")
        return
    print("[System: Document parsed successfully. Extracting skills and matching jobs...]")

    initial_msg = Msg(
        name="User",
        content=f"Here is my extracted resume content:\n{user_resume_text}\n\nPlease search for matching jobs.",
        role="user",
    )

    print("\n[System: JobSearch Agent is scanning LinkedIn...]")
    search_response = await job_search_agent(initial_msg)

    print("\n[System: JobPost Agent is evaluating and ranking the jobs based on your resume...]")
    eval_msg = Msg(
        name="System",
        content=(
            f"User's Resume Background:\n{user_resume_text}\n\n"
            f"Jobs found by JobSearch Agent (JSON):\n{search_response.content}\n\n"
            "Please rank them and provide recommendation reasons in JSON format."
        ),
        role="user",
    )
    response = await job_post_agent(eval_msg)
    latest_ranked_jobs_json = str(response.content)
    print_final_reply(response)

    session_state = {
        "resume_content": user_resume_text,
        "selected_job": None,
        "last_agent_output": str(response.content)[:500],
        "workflow_stage": "discovery",
    }

    while True:
        user_input = await user_agent()
        if user_input.content.lower() in ["exit", "quit"]:
            break

        # --- Orchestrator routing ---
        routing_context = (
            f"User message: {user_input.content}\n"
            f"Current workflow stage: {session_state['workflow_stage']}\n"
            f"Selected job: {session_state['selected_job'] or 'None yet'}\n"
            f"Last agent output summary: {session_state['last_agent_output'][:200]}"
        )
        routing_msg = Msg(name="User", content=routing_context, role="user")

        print("\n[System: Orchestrator is analysing your intent...]")
        route_response = await orchestrator_agent(routing_msg)
        route = parse_routing_decision(route_response)
        if not route:
            print("[System: Orchestrator fallback → keyword routing]")
            route = keyword_fallback(user_input.content.lower())
        print(f"[System: Routed to → {route}]")

        # --- Dispatch ---
        if route == "resume_tailor":
            context_msg = build_context_message(
                session_state["resume_content"], latest_ranked_jobs_json,
                user_input.content, session_state["selected_job"],
            )
            response = await resume_tailor_agent(context_msg)
            session_state["workflow_stage"] = "tailoring"

        elif route == "interview_prep":
            context_msg = build_context_message(
                session_state["resume_content"], latest_ranked_jobs_json,
                user_input.content, session_state["selected_job"],
            )
            response = await interview_prep_agent(context_msg)
            session_state["workflow_stage"] = "preparation"

        elif route == "general":
            print(
                "\n[Orchestrator]: I'm your AI Job Search Companion. You can ask me to:\n"
                "  - Search for jobs\n"
                "  - Tailor your resume for a specific role\n"
                "  - Prepare for interviews\n"
                "Type 'exit' to quit."
            )
            continue

        else:  # job_search
            print("\n[System: JobSearch Agent is scanning LinkedIn...]")
            search_response = await job_search_agent(user_input)
            print("\n[System: JobPost Agent is evaluating and ranking the jobs...]")
            eval_msg = Msg(
                name="System",
                content=(
                    f"User's Resume Background:\n{user_resume_text}\n\n"
                    f"User's Request:\n{user_input.content}\n\n"
                    f"Jobs found by JobSearch Agent (JSON):\n{search_response.content}\n\n"
                    "Please rank them and provide recommendation reasons in JSON format."
                ),
                role="user",
            )
            response = await job_post_agent(eval_msg)
            latest_ranked_jobs_json = str(response.content)
            session_state["workflow_stage"] = "discovery"

        session_state["last_agent_output"] = str(response.content)[:500]
        print_final_reply(response)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except EnvironmentError as exc:
        print(f"\n[System Error]: {exc}")
    except AuthenticationError as exc:
        print(f"\n[System Error]: API key 无效或已失效。详细信息: {exc}")
    except APIConnectionError as exc:
        print(f"\n[System Error]: 无法连接到 API。请检查网络或代理设置。详细信息: {exc}")
    except APIStatusError as exc:
        print(f"\n[System Error]: API 返回异常状态码 {exc.status_code}。详细信息: {exc}")
