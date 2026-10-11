$BaseUrl = "http://127.0.0.1:8000"

$ApproveProductId = 29
$RejectProductId  = 30
$ConversationId   = 13

function Get-Token($username, $password) {
    $body = @{ username = $username; password = $password } | ConvertTo-Json
    $resp = Invoke-WebRequest -Uri "$BaseUrl/api/token/" -Method POST -ContentType "application/json" -Body $body
    return ($resp.Content | ConvertFrom-Json).access
}

function Show-Result($label, $scriptBlock) {
    Write-Host "`n=== $label ===" -ForegroundColor Cyan
    try {
        $result = & $scriptBlock
        Write-Host $result -ForegroundColor Green
    } catch {
        Write-Host "Status: $($_.Exception.Response.StatusCode)" -ForegroundColor Yellow
        Write-Host $_.ErrorDetails.Message -ForegroundColor Red
    }
}

$fedounToken = Get-Token "fedoun" "testpass123"
$leilaToken  = Get-Token "leila" "testpass123"

Show-Result "Register push token (fedoun)" {
    $body = @{ expo_push_token = "ExponentPushToken[real-device-token-9999]" } | ConvertTo-Json
    (Invoke-WebRequest -Uri "$BaseUrl/api/accounts/push-token/" -Method POST -ContentType "application/json" `
        -Headers @{ Authorization = "Bearer $fedounToken" } -Body $body).Content
}

Show-Result "Approve product $ApproveProductId (fedoun, staff)" {
    $body = @{ status = "approved" } | ConvertTo-Json
    (Invoke-WebRequest -Uri "$BaseUrl/api/catalog/products/$ApproveProductId/approve/" -Method PATCH -ContentType "application/json" `
        -Headers @{ Authorization = "Bearer $fedounToken" } -Body $body).Content
}

Show-Result "Reject product $RejectProductId (fedoun, staff)" {
    $body = @{ status = "rejected" } | ConvertTo-Json
    (Invoke-WebRequest -Uri "$BaseUrl/api/catalog/products/$RejectProductId/approve/" -Method PATCH -ContentType "application/json" `
        -Headers @{ Authorization = "Bearer $fedounToken" } -Body $body).Content
}

Show-Result "Approve attempt by non-staff (leila) -> expect 403" {
    $body = @{ status = "approved" } | ConvertTo-Json
    (Invoke-WebRequest -Uri "$BaseUrl/api/catalog/products/$ApproveProductId/approve/" -Method PATCH -ContentType "application/json" `
        -Headers @{ Authorization = "Bearer $leilaToken" } -Body $body).Content
}

Show-Result "Send message on conversation $ConversationId (fedoun)" {
    $body = @{ conversation = $ConversationId; text = "Test message from script" } | ConvertTo-Json
    (Invoke-WebRequest -Uri "$BaseUrl/api/catalog/messages/send/" -Method POST -ContentType "application/json" `
        -Headers @{ Authorization = "Bearer $fedounToken" } -Body $body).Content
}

Show-Result "Update conversation $ConversationId status to confirmed (fedoun)" {
    $body = @{ status = "confirmed" } | ConvertTo-Json
    (Invoke-WebRequest -Uri "$BaseUrl/api/catalog/conversations/$ConversationId/status/" -Method PATCH -ContentType "application/json" `
        -Headers @{ Authorization = "Bearer $fedounToken" } -Body $body).Content
}

Show-Result "Invalid status value -> expect 400" {
    $body = @{ status = "invalid_status" } | ConvertTo-Json
    (Invoke-WebRequest -Uri "$BaseUrl/api/catalog/products/$ApproveProductId/approve/" -Method PATCH -ContentType "application/json" `
        -Headers @{ Authorization = "Bearer $fedounToken" } -Body $body).Content
}

Show-Result "Nonexistent product -> expect 404" {
    $body = @{ status = "approved" } | ConvertTo-Json
    (Invoke-WebRequest -Uri "$BaseUrl/api/catalog/products/99999/approve/" -Method PATCH -ContentType "application/json" `
        -Headers @{ Authorization = "Bearer $fedounToken" } -Body $body).Content
}

Write-Host "`n`nDone. Now check the 'runserver' terminal for [push] log lines to confirm notifications fired." -ForegroundColor Magenta