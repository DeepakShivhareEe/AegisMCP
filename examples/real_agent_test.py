#!/usr/bin/env python3
"""
AegisMCP Real Agent Test Script

Demonstrates 3 real scenarios against a running AegisMCP gateway:
1. Safe RAG + read query that passes through cleanly
2. Destructive SQL query (DROP TABLE) that gets intercepted and blocked
3. Sensitive production action (Stripe refund $450) that pauses for HITL approval

Prerequisites:
- AegisMCP backend running on http://localhost:8000
- Frontend running on http://localhost:3000 (for HITL approval UI)
- An API key generated from the "API Keys & SDK" tab in the frontend

Environment variables:
- AEGIS_API_KEY: Your API key (aegis_live_...)
- AEGIS_BASE_URL: Gateway URL (default: http://localhost:8000)
"""

import os
import sys
import time
import json
from typing import Any, Dict

# Add sdk to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

from aegis_sdk import AegisClient, AegisGuardrailBlockedError, AegisHITLRejectedError, AegisConnectionError


def print_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_step(step: str) -> None:
    print(f"\n  ▶ {step}")


def print_success(msg: str) -> None:
    print(f"  ✓ {msg}")


def print_error(msg: str) -> None:
    print(f"  ✗ {msg}")


def print_info(msg: str) -> None:
    print(f"  ℹ {msg}")


# ============================================================================
# Scenario 1: Safe RAG + Read Query
# ============================================================================
def scenario_safe_rag_query(client: AegisClient) -> None:
    print_header("SCENARIO 1: Safe RAG + Read Query")
    print_info("This should pass through cleanly - read-only, no sensitive patterns")

    @client.guard_tool("filesystem-sandbox-mcp", "search_documents", span_type="RAG_RETRIEVAL")
    def search_knowledge_base(query: str, top_k: int = 5) -> Dict[str, Any]:
        """Simulated RAG search - safe read operation."""
        print_step(f"Executing RAG search: '{query}'")
        time.sleep(0.1)  # Simulate work
        return {
            "results": [
                {"id": "doc-1", "title": "Company Policy", "score": 0.95},
                {"id": "doc-2", "title": "Security Guidelines", "score": 0.87},
            ],
            "query": query,
            "top_k": top_k,
        }

    try:
        result = search_knowledge_base("How to reset password?", top_k=3)
        print_success(f"RAG search completed! Found {len(result['results'])} documents")
        print_info(f"Result: {json.dumps(result, indent=2)}")
    except AegisGuardrailBlockedError as e:
        print_error(f"Blocked by guardrails: {e.reason}")
    except AegisHITLRejectedError as e:
        print_error(f"Rejected by HITL: {e.reason}")
    except Exception as e:
        print_error(f"Unexpected error: {e}")


# ============================================================================
# Scenario 2: Destructive SQL Query (DROP TABLE)
# ============================================================================
def scenario_destructive_sql(client: AegisClient) -> None:
    print_header("SCENARIO 2: Destructive SQL Query (DROP TABLE)")
    print_info("This should be BLOCKED before execution - contains destructive pattern")

    executed = {"flag": False}

    @client.guard_tool("postgres-prod-mcp", "execute_query")
    def execute_sql(query: str) -> Dict[str, Any]:
        """Simulated SQL execution - would be dangerous!"""
        executed["flag"] = True
        print_step(f"Executing SQL: {query}")
        time.sleep(0.1)
        return {"rows_affected": 0, "query": query}

    try:
        # This contains a blocked pattern - should be intercepted
        result = execute_sql("DROP TABLE customers;")
        print_error(f"SHOULD NOT REACH HERE! Result: {result}")
    except AegisGuardrailBlockedError as e:
        print_success("Correctly blocked by guardrails!")
        print_info(f"Reason: {e.reason}")
        print_info(f"Trace ID: {e.trace_id}, Span ID: {e.span_id}")
        if executed["flag"]:
            print_error("Tool body executed before enforcement! Pre-flight failed.")
        else:
            print_success("Tool body never executed (pre-flight enforcement).")
    except AegisHITLRejectedError as e:
        print_error(f"Unexpected HITL rejection: {e.reason}")
    except Exception as e:
        print_error(f"Unexpected error: {e}")


# ============================================================================
# Scenario 3: Sensitive Production Action (Stripe Refund $450)
# ============================================================================
def scenario_stripe_refund_hitl(client: AegisClient) -> None:
    print_header("SCENARIO 3: Stripe Refund $450 (HITL Required)")
    print_info("This will PAUSE for Human-in-the-Loop approval")
    print_info("Go to http://localhost:3000 → HITL Approval Queue to Approve/Reject")

    @client.guard_tool("stripe-billing-mcp", "create_refund")
    def create_stripe_refund(amount_cents: int, currency: str, reason: str) -> Dict[str, Any]:
        """Simulated Stripe refund - sensitive production action."""
        print_step(f"Creating refund: ${amount_cents/100:.2f} {currency.upper()} ({reason})")
        time.sleep(0.1)
        return {
            "id": f"re_{os.urandom(8).hex()}",
            "amount": amount_cents,
            "currency": currency,
            "reason": reason,
            "status": "succeeded",
        }

    try:
        print_step("Calling Stripe refund - will pause for HITL...")
        result = create_stripe_refund(45000, "usd", "customer_request")
        print_success(f"Refund approved and executed!")
        print_info(f"Result: {json.dumps(result, indent=2)}")
    except AegisGuardrailBlockedError as e:
        print_error(f"Blocked by guardrails: {e.reason}")
    except AegisHITLRejectedError as e:
        print_error(f"Rejected by human operator!")
        print_info(f"Reason: {e.reason}")
        print_info(f"Trace ID: {e.trace_id}, Span ID: {e.span_id}")
    except Exception as e:
        print_error(f"Unexpected error: {e}")


# ============================================================================
# Main
# ============================================================================
def main() -> None:
    # Load configuration from environment
    api_key = os.getenv("AEGIS_API_KEY")
    base_url = os.getenv("AEGIS_BASE_URL", "http://localhost:8000")

    if not api_key:
        print_error("AEGIS_API_KEY environment variable not set!")
        print_info("Get an API key from the AegisMCP dashboard: http://localhost:3000")
        print_info("Go to 'API Keys & SDK' tab → Create New API Key")
        sys.exit(1)

    if not api_key.startswith("aegis_live_"):
        print_error("Invalid API key format. Should start with 'aegis_live_'")
        sys.exit(1)

    print_header("AEGISMCP REAL AGENT TEST")
    print_info(f"Gateway: {base_url}")
    print_info(f"API Key: {api_key[:20]}...")

    # Test connection
    print_step("Testing connection to AegisMCP gateway...")
    try:
        with AegisClient(api_key=api_key, base_url=base_url) as client:
            # Quick health check via intercept endpoint
            response = client._request("GET", "/api/v1/health")
            print_success(f"Connected! Gateway status: {response.json()}")
    except AegisConnectionError as e:
        print_error(f"Cannot connect to gateway: {e}")
        print_info("Make sure the backend is running: docker-compose up -d")
        sys.exit(1)
    except Exception as e:
        print_error(f"Connection test failed: {e}")
        sys.exit(1)

    # Run scenarios
    with AegisClient(api_key=api_key, base_url=base_url) as client:
        scenario_safe_rag_query(client)
        time.sleep(1)

        scenario_destructive_sql(client)
        time.sleep(1)

        scenario_stripe_refund_hitl(client)

    print_header("ALL SCENARIOS COMPLETED")
    print_info("Check the AegisMCP dashboard at http://localhost:3000 for trace details")


if __name__ == "__main__":
    main()