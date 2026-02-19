from app.services.agents.tools.approval import APPROVAL_SPEC, request_user_approval
from app.services.agents.tools.benchmarks import BENCHMARKS_SPEC, get_industry_benchmarks
from app.services.agents.tools.chat import CHAT_SPEC, post_to_chat
from app.services.agents.tools.create_campaign import CREATE_CAMPAIGN_SPEC, create_campaign_tool
from app.services.agents.tools.execute_campaign import (
    EXECUTE_CAMPAIGN_SPEC,
    execute_campaign_on_platform,
)
from app.services.agents.tools.manage_campaign import (
    PAUSE_CAMPAIGN_SPEC,
    RESUME_CAMPAIGN_SPEC,
    UPDATE_BUDGET_SPEC,
    pause_platform_campaign,
    resume_platform_campaign,
    update_platform_budget,
)
from app.services.agents.tools.predict import PREDICT_SPEC, predict_campaign_performance
from app.services.agents.tools.query_campaigns import QUERY_CAMPAIGNS_SPEC, query_past_campaigns
from app.services.agents.tools.search_web import SEARCH_WEB_SPEC, search_web

ALL_TOOL_SPECS = [
    SEARCH_WEB_SPEC,
    BENCHMARKS_SPEC,
    QUERY_CAMPAIGNS_SPEC,
    PREDICT_SPEC,
    CREATE_CAMPAIGN_SPEC,
    CHAT_SPEC,
    APPROVAL_SPEC,
    EXECUTE_CAMPAIGN_SPEC,
    PAUSE_CAMPAIGN_SPEC,
    RESUME_CAMPAIGN_SPEC,
    UPDATE_BUDGET_SPEC,
]

ALL_TOOL_HANDLERS = {
    "search_web": search_web,
    "get_industry_benchmarks": get_industry_benchmarks,
    "query_past_campaigns": query_past_campaigns,
    "predict_campaign_performance": predict_campaign_performance,
    "create_campaign": create_campaign_tool,
    "post_to_chat": post_to_chat,
    "request_user_approval": request_user_approval,
    "execute_campaign_on_platform": execute_campaign_on_platform,
    "pause_platform_campaign": pause_platform_campaign,
    "resume_platform_campaign": resume_platform_campaign,
    "update_platform_budget": update_platform_budget,
}
