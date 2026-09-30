Attribute VB_Name = "PrivateEngineBridge"
Option Explicit

' Protocol 1.0. Import ONLY into a separately reviewed, dedicated workbook.
' No Workbook_Open, worksheet order formulas, auto-login, or macro-security edits.
' Python must reserve request IDs durably before invoking this one entry point.

Private Function BridgeNamed(ByVal name As String) As Range
    Set BridgeNamed = ThisWorkbook.Names(name).RefersToRange
End Function

Public Sub BridgeExecute()
    Dim cmd As String
    Dim broker As String
    Dim requestId As Variant
    Dim argc As Long
    Dim a(1 To 19) As Variant
    Dim i As Long
    Dim raw As Variant

    On Error GoTo Uncertain
    BridgeNamed("BridgeResponseStatus").Value2 = "UNKNOWN"
    BridgeNamed("BridgeResponseValue").Value2 = ""
    BridgeNamed("BridgeResponseRequestID").Value2 = ""
    If CStr(BridgeNamed("BridgeProtocolVersion").Value2) <> "1.0" Then Err.Raise 5, , "protocol version mismatch"
    If Len(CStr(BridgeNamed("BridgeGeneration").Value2)) = 0 Then Err.Raise 5, , "generation missing"
    requestId = BridgeNamed("BridgeRequestID").Value2
    If Not IsNumeric(requestId) Then Err.Raise 5, , "request ID missing"
    cmd = CStr(BridgeNamed("BridgeCommand").Value2)
    broker = CStr(BridgeNamed("BridgeBroker").Value2)
    argc = CLng(BridgeNamed("BridgeArgCount").Value2)
    If argc < 2 Or argc > 19 Then Err.Raise 5, , "argument count unsupported"
    For i = 1 To argc
        a(i) = BridgeNamed("BridgeArgs").Cells(i, 1).Value2
    Next i
    If CStr(a(1)) <> CStr(requestId) Then Err.Raise 5, , "request ID mismatch"

    Select Case broker & ":" & cmd
        Case "rakuten:RssStockOrder_V"
            If argc <> 19 Then Err.Raise 5, , "Rakuten order arity"
            raw = Application.Run("RssStockOrder_V", a(1), a(2), a(3), a(4), a(5), a(6), a(7), a(8), a(9), a(10), a(11), a(12), a(13), a(14), a(15), a(16), a(17), a(18), a(19))
        Case "rakuten:RssCancelOrder_V"
            If argc <> 2 Then Err.Raise 5, , "Rakuten cancel arity"
            raw = Application.Run("RssCancelOrder_V", a(1), a(2))
        Case "neotrade:SntExecEqtyOrder"
            If argc <> 11 Then Err.Raise 5, , "NeoTrade order arity"
            raw = Application.Run("SntExecEqtyOrder", a(1), a(2), a(3), a(4), a(5), a(6), a(7), a(8), a(9), a(10), a(11))
        Case "neotrade:SntExecCancelOrder"
            If argc <> 3 Then Err.Raise 5, , "NeoTrade cancel arity"
            raw = Application.Run("SntExecCancelOrder", a(1), a(2), a(3))
        Case Else
            Err.Raise 5, , "command not on bridge allowlist"
    End Select

    ' A VBA return is not proof of broker acceptance or a fill. Query separately.
    BridgeNamed("BridgeResponseValue").Value2 = Left$(CStr(raw), 250)
    BridgeNamed("BridgeResponseRequestID").Value2 = requestId
    BridgeNamed("BridgeResponseStatus").Value2 = "UNKNOWN"
    Exit Sub

Uncertain:
    On Error Resume Next
    BridgeNamed("BridgeResponseValue").Value2 = Left$("VBA error " & CStr(Err.Number), 250)
    BridgeNamed("BridgeResponseRequestID").Value2 = requestId
    BridgeNamed("BridgeResponseStatus").Value2 = "UNKNOWN"
End Sub
