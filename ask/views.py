from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from exact_oauth.services import get_service
from .services import Intent, Filter, Op
import json
import os


def home(request):
    # Create a sample Intent object for demonstration
    sample_intent = Intent(
        tool_call="get_sales_invoices",
        description="Get recent sales invoices from the current year",
        filters=[
            Filter(field="status", op=Op.IN, values=["open", "paid"]),
            Filter(field="department", op=Op.EQ, value="sales"),
            Filter(field="amount", op=Op.GT, value=1000),
        ],
    )

    context = {"user_intent": sample_intent}
    return render(request, "ask/home.html", context)


@require_http_methods(["GET"])
def api_forwarder(request, path):
    try:
        session_key = request.session.session_key
        if not session_key:
            return JsonResponse({"error": "No session available"}, status=401)

        service = get_service(session_key)

        query_params = request.GET.dict()

        response = service.get(path, params=query_params)

        if response.status_code == 200:
            return JsonResponse(response.json(), safe=False)
        else:
            return JsonResponse(
                {
                    "error": f"Exact API returned status {response.status_code}",
                    "details": response.text,
                },
                status=response.status_code,
            )

    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"error": "Internal server error"}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def ai_chat(request):
    """
    Chat endpoint that uses OpenAI with Exact Online APIs as tools.
    """
    print(f"🌐 Django View: Received AI chat request")

    try:
        # Get session key for authentication
        session_key = request.session.session_key
        print(
            f"🔑 Django View: Session key: {session_key[:8] if session_key else 'None'}..."
        )

        if not session_key:
            print(f"❌ Django View: No session available")
            return JsonResponse({"error": "No session available"}, status=401)

        # Get OpenAI API key from environment
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            print(f"❌ Django View: OpenAI API key not configured")
            return JsonResponse({"error": "OpenAI API key not configured"}, status=500)
        print(f"🤖 Django View: OpenAI API key found")

        # Parse request body
        try:
            data = json.loads(request.body)
            message = data.get("message", "").strip()
            print(f"💬 Django View: User message: '{message}'")
            if not message:
                return JsonResponse({"error": "Message is required"}, status=400)
        except json.JSONDecodeError:
            print(f"❌ Django View: Invalid JSON in request body")
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        # Import and use the AI client
        from .services import IntentFormer

        print(f"🚀 Django View: Creating AI client and processing request...")
        client = IntentFormer(openai_api_key, session_key)
        response = client.chat(message)

        print(f"✅ Django View: Got AI response, length: {len(response)}")
        return JsonResponse({"response": response, "message": message})

    except ValueError as e:
        print(f"❌ Django View: ValueError: {e}")
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        print(f"❌ Django View: Exception: {e}")
        return JsonResponse({"error": "Internal server error"}, status=500)


def test_intent(request):
    """Test page for IntentFormer to see Intent objects."""
    import os
    import time
    
    intent = None
    debug_info = None
    message = None
    
    if request.method == "POST":
        message = request.POST.get("message", "").strip()
        
        if not message:
            return render(request, "ask/test_intent.html", {
                "error": "Please enter a message",
                "message": message
            })
        
        # Check for OpenAI API key
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            return render(request, "ask/test_intent.html", {
                "error": "OpenAI API key not configured",
                "message": message
            })
        
        try:
            # Get session key (dummy for testing)
            session_key = "test_session"
            
            # Import and create IntentFormer
            from .services import IntentFormer
            
            start_time = time.time()
            intent_former = IntentFormer(openai_api_key, session_key)
            
            # Parse the intent
            intent = intent_former.parse_intent(message)
            processing_time = int((time.time() - start_time) * 1000)
            
            # Create debug info
            debug_info = {
                "selected_tool": intent.tool_call,
                "fields_count": len(intent.filters) if intent.filters else 0,
                "processing_time": processing_time
            }
            
        except Exception as e:
            print(f"❌ Test Intent View: Error: {e}")
            return render(request, "ask/test_intent.html", {
                "error": f"Error processing intent: {str(e)}",
                "message": message
            })
    
    return render(request, "ask/test_intent.html", {
        "intent": intent,
        "debug_info": debug_info,
        "message": message
    })
