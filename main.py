import wx

from kicad_nextpcb_new.import_BOM_view.import_BOM_dailog import ImportBOMDailog

app = wx.App()

dialog = ImportBOMDailog(parent=None)

dialog.Show()
app.MainLoop()