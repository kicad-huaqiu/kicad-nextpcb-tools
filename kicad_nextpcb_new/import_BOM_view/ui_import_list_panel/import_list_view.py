import wx
import wx.xrc
import wx.dataview
import wx.dataview as dv


from .ui_import_list_panel import UiImportListPanel


class ImportListView(UiImportListPanel):
    def __init__(self, parent, id=wx.ID_ANY, pos=wx.DefaultPosition, size=wx.DefaultSize, style=wx.TAB_TRAVERSAL, name=wx.EmptyString):
        super().__init__(parent, id=id, pos=pos, size=size, style=style, name=name)


        self.show_list.AppendTextColumn(
            "index",
            width=60, mode=dv.DATAVIEW_CELL_ACTIVATABLE, align=wx.ALIGN_LEFT)
        self.show_list.AppendTextColumn(
            "Reference",
            width=80, mode=dv.DATAVIEW_CELL_ACTIVATABLE, align=wx.ALIGN_LEFT)
        self.show_list.AppendTextColumn(
            "Value",
            width=100, mode=dv.DATAVIEW_CELL_ACTIVATABLE, align=wx.ALIGN_LEFT)
        self.show_list.AppendTextColumn(
            "Footprint",
            width=300, mode=dv.DATAVIEW_CELL_ACTIVATABLE, align=wx.ALIGN_LEFT)
        self.show_list.AppendTextColumn(
            "MPN",
            width=100, mode=dv.DATAVIEW_CELL_ACTIVATABLE, align=wx.ALIGN_LEFT)
        self.show_list.AppendTextColumn(
            "Manufacturer",
            width=200, mode=dv.DATAVIEW_CELL_ACTIVATABLE, align=wx.ALIGN_LEFT)
        self.show_list.AppendTextColumn(
            "Description",
            width=200, mode=dv.DATAVIEW_CELL_ACTIVATABLE, align=wx.ALIGN_LEFT)
        self.show_list.AppendTextColumn(
            "Quantity",
            width=80, mode=dv.DATAVIEW_CELL_ACTIVATABLE, align=wx.ALIGN_LEFT)

