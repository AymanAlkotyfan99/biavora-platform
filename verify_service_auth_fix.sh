#!/bin/bash
# Verification script for service-to-service authentication fix

echo "=========================================="
echo "Service-to-Service Auth Fix Verification"
echo "=========================================="
echo ""

# Check if .env.microservices has SERVICE_INTERNAL_TOKEN
echo "1. Checking .env.microservices for SERVICE_INTERNAL_TOKEN..."
if grep -q "^SERVICE_INTERNAL_TOKEN=" .env.microservices; then
    TOKEN_VALUE=$(grep "^SERVICE_INTERNAL_TOKEN=" .env.microservices | cut -d'=' -f2)
    TOKEN_LENGTH=${#TOKEN_VALUE}
    echo "   ✅ SERVICE_INTERNAL_TOKEN found (length: $TOKEN_LENGTH)"
    if [ $TOKEN_LENGTH -lt 32 ]; then
        echo "   ⚠️  WARNING: Token is short. Recommended: 32+ characters"
    fi
else
    echo "   ❌ SERVICE_INTERNAL_TOKEN not found in .env.microservices"
    exit 1
fi

# Check docker-compose.yml has SERVICE_INTERNAL_TOKEN mapped
echo ""
echo "2. Checking docker-compose.yml for SERVICE_INTERNAL_TOKEN mapping..."
if grep -q "SERVICE_INTERNAL_TOKEN:" docker-compose.yml; then
    COUNT=$(grep -c "SERVICE_INTERNAL_TOKEN:" docker-compose.yml)
    echo "   ✅ SERVICE_INTERNAL_TOKEN mapped in docker-compose.yml ($COUNT occurrences)"
else
    echo "   ❌ SERVICE_INTERNAL_TOKEN not mapped in docker-compose.yml"
    exit 1
fi

# Check ai-service has the enhanced query_service_auth.py
echo ""
echo "3. Checking ai-service query_service_auth.py for logging..."
if grep -q "logger.info" services/ai-service/shared/query_service_auth.py; then
    echo "   ✅ Logging added to query_service_auth.py"
else
    echo "   ❌ Logging not found in query_service_auth.py"
    exit 1
fi

# Check ai-service settings.py has startup validation
echo ""
echo "4. Checking ai-service settings.py for startup validation..."
if grep -q "SERVICE_INTERNAL_TOKEN not configured" services/ai-service/backend/settings.py; then
    echo "   ✅ Startup validation added to ai-service settings.py"
else
    echo "   ❌ Startup validation not found in ai-service settings.py"
    exit 1
fi

# Check query-service settings.py has startup validation
echo ""
echo "5. Checking query-service settings.py for startup validation..."
if grep -q "SERVICE_INTERNAL_TOKEN configured" services/query-service/service_config/settings.py; then
    echo "   ✅ Startup validation added to query-service settings.py"
else
    echo "   ❌ Startup validation not found in query-service settings.py"
    exit 1
fi

# Check test script exists
echo ""
echo "6. Checking test script exists..."
if [ -f "services/test_service_auth.py" ]; then
    echo "   ✅ Test script created: services/test_service_auth.py"
else
    echo "   ❌ Test script not found"
    exit 1
fi

echo ""
echo "=========================================="
echo "✅ All verification checks passed!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Restart services: docker-compose restart ai-service query-service"
echo "2. Check logs: docker-compose logs ai-service | grep SERVICE_INTERNAL_TOKEN"
echo "3. Run tests: python services/test_service_auth.py"
echo ""
