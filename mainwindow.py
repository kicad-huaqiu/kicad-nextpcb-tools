import json
import logging
import os
import re
import sys

import wx
import wx.adv as adv
import wx.dataview
import requests
import webbrowser
import threading
from pcbnew import GetBoard, GetBuildVersion, ToMM
from .debug import Print
from .events import (
    EVT_ASSIGN_PARTS_EVENT,
    EVT_MESSAGE_EVENT,
    EVT_POPULATE_FOOTPRINT_LIST_EVENT,
    EVT_RESET_GAUGE_EVENT,
    EVT_UPDATE_GAUGE_EVENT,
    EVT_UPDATE_SETTING,
)
from .fabrication import Fabrication
from .helpers import (
    PLUGIN_PATH,
    GetScaleFactor,
    HighResWxSize,
    get_footprint_by_ref,
    getVersion,
    loadBitmapScaled,
)
from .library import Library, LibraryState
from .partdetails import PartDetailsDialog
from .partmapper import PartMapperManagerDialog
from .partselector import PartSelectorDialog
from .rotations import RotationManagerDialog
from .schematicexport import SchematicExport
from .settings import SettingsDialog
from .store import Store

logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

ID_GROUP = 0
ID_AUTO_MATCH = 1
ID_GENERATE = 2
ID_GENERATE_AND_PLACE_ORDER = 3
ID_ROTATIONS = 4
ID_MAPPINGS = 5
ID_SETTINGS = 6

ID_MANUAL_MATCH = 7
ID_REMOVE_PART = 8
ID_SELECT_SAME_PARTS = 9
ID_PART_DETAILS = 10
ID_TOGGLE_BOM = 11
ID_TOGGLE_POS = 12
ID_SAVE_MAPPINGS = 13
ID_COPY_MPN = wx.NewIdRef()
ID_PASTE_MPN = wx.NewIdRef()
ID_CONTEXT_MENU_ADD_ROT_BY_PACKAGE = wx.NewIdRef()
ID_CONTEXT_MENU_ADD_ROT_BY_NAME = wx.NewIdRef()
#ID_EXPORT_TO_SCHEMATIC = 16


class FootPrintList(wx.dataview.DataViewListCtrl):
    def __init__(
            self,
            parent,
            mainwindows,
            id=wx.ID_ANY,
            pos=wx.DefaultPosition,
            size=wx.DefaultSize,
            style=wx.dataview.DV_MULTIPLE):
        wx.dataview.DataViewListCtrl.__init__(self, parent, id, pos, size, style)
        
        self.SetMinSize(HighResWxSize(mainwindows.window, wx.Size(900, 400)))
        self.idx = self.AppendTextColumn(
            "index",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(mainwindows.scale_factor * 50),
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.reference = self.AppendTextColumn(
            "Reference",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(mainwindows.scale_factor * 80),
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.value = self.AppendTextColumn(
            "Value",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(mainwindows.scale_factor * 100),
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.footprint = self.AppendTextColumn(
            "Footprint",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(mainwindows.scale_factor * 300),
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.lcsc = self.AppendTextColumn(
            "MPN",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(mainwindows.scale_factor * 100),
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.type_column = self.AppendTextColumn(
            "Manufacturer",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(mainwindows.scale_factor * 200),
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.stock = self.AppendTextColumn(
            "Description",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(mainwindows.scale_factor * 200),
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.bom = self.AppendToggleColumn(
            "BOM",
            mode=wx.dataview.DATAVIEW_CELL_ACTIVATABLE,
            width=int(mainwindows.scale_factor * 60),
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.pos = self.AppendToggleColumn(
            "POS",
            mode=wx.dataview.DATAVIEW_CELL_ACTIVATABLE,
            width=int(mainwindows.scale_factor * 60),
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.rot = self.AppendTextColumn(
            "Rotation",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(mainwindows.scale_factor * 80),
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.side = self.AppendTextColumn(
            "Side",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(mainwindows.scale_factor * 50),
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.AppendTextColumn(
            "",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=1,
            align=wx.ALIGN_CENTER,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        #table_sizer.Add(self.footprint_list, 20, wx.ALL | wx.EXPAND, 5)
        self.Bind(
            wx.dataview.EVT_DATAVIEW_COLUMN_HEADER_CLICK, mainwindows.OnSortFootprintList
        )
        self.Bind(
            wx.dataview.EVT_DATAVIEW_SELECTION_CHANGED, mainwindows.OnFootprintSelected
        )
        self.Bind(
            wx.dataview.EVT_DATAVIEW_ITEM_CONTEXT_MENU, mainwindows.OnRightDown
        )
        self.Bind(wx.dataview.EVT_DATAVIEW_ITEM_ACTIVATED, mainwindows.get_part_details)
        self.Bind(wx.dataview.EVT_DATAVIEW_ITEM_VALUE_CHANGED, mainwindows.toggle_update_to_db)

class NextPCBTools(wx.Dialog):
    def __init__(self, parent):
        if sys.platform != "darwin":
            self.app = wx.App()
        wx.Dialog.__init__(
            self,
            parent,
            id=wx.ID_ANY,
            title=f"NextPCB Tools [ {getVersion()} ]",
            pos=wx.DefaultPosition,
            size=wx.Size(1400, 800),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
        )
        self.KicadBuildVersion = GetBuildVersion()
        self.window = wx.GetTopLevelParent(self)
        self.SetSize(HighResWxSize(self.window, wx.Size(1400, 800)))
        self.scale_factor = GetScaleFactor(self.window)
        self.project_path = os.path.split(GetBoard().GetFileName())[0]
        self.board_name = os.path.split(GetBoard().GetFileName())[1]
        self.schematic_name = f"{self.board_name.split('.')[0]}.kicad_sch"
        self.hide_bom_parts = False
        self.hide_pos_parts = False
        self.manufacturers = []
        self.packages = []
        self.library = None
        self.store = None
        self.settings = None
        self.group_strategy = 0
        self.load_settings()
        self.Bind(wx.EVT_CLOSE, self.quit_dialog)

        # ---------------------------------------------------------------------
        # ---------------------------- Hotkeys --------------------------------
        # ---------------------------------------------------------------------
        quitid = wx.NewId()
        self.Bind(wx.EVT_MENU, self.quit_dialog, id=quitid)

        entries = [wx.AcceleratorEntry(), wx.AcceleratorEntry(), wx.AcceleratorEntry()]
        entries[0].Set(wx.ACCEL_CTRL, ord("W"), quitid)
        entries[1].Set(wx.ACCEL_CTRL, ord("Q"), quitid)
        entries[2].Set(wx.ACCEL_SHIFT, wx.WXK_ESCAPE, quitid)
        accel = wx.AcceleratorTable(entries)
        self.SetAcceleratorTable(accel)

        # ---------------------------------------------------------------------
        # -------------------- Horizontal top buttons -------------------------
        # ---------------------------------------------------------------------

        self.upper_toolbar = wx.ToolBar(
            self,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.Size(1400, -1),
            wx.TB_HORIZONTAL | wx.TB_TEXT | wx.TB_HORZ_LAYOUT | wx.TB_NODIVIDER
        )
        self.upper_toolbar.SetToolBitmapSize((24, 24))
        self.group_label = wx.StaticText(self.upper_toolbar, wx.ID_ANY, label=" Group by: ")

        self.group_label.Wrap(-1)
        self.upper_toolbar.AddControl(self.group_label)

        self.upper_toolbar.AddSeparator()

        group_strategy_value = [" No Group ", " Value & Footprint "]

        self.cb_group_strategy = wx.ComboBox(
            self.upper_toolbar,
            ID_GROUP,
            "No Group",
             wx.DefaultPosition,
             wx.DefaultSize,
            group_strategy_value,
            style=wx.CB_DROPDOWN | wx.CB_READONLY
        )

        self.cb_group_strategy.SetSelection(0)

        self.upper_toolbar.AddControl(self.cb_group_strategy)

        self.upper_toolbar.AddSeparator()

        self.auto_match_button = self.upper_toolbar.AddTool(
            ID_AUTO_MATCH,
            "Auto Match ",
            loadBitmapScaled("nextpcb-automatch.png", self.scale_factor),
            "Auto Match MPN number to parts",
        )

        self.upper_toolbar.AddStretchableSpace()

        self.generate_button = wx.Button(
            self.upper_toolbar,
            ID_GENERATE,
            " Generate ",
            wx.DefaultPosition,
            wx.DefaultSize,
            0
        )
        self.upper_toolbar.AddControl(self.generate_button)
        self.upper_toolbar.SetToolLongHelp(
            ID_GENERATE,
            "Generate files and Place Order"
        )

        self.generate_place_order_button = wx.Button(
            self.upper_toolbar,
            ID_GENERATE_AND_PLACE_ORDER,
            " Generate and Place Order ",
            wx.DefaultPosition,
            wx.DefaultSize,
            0
        )
        self.upper_toolbar.AddControl(self.generate_place_order_button)
        self.upper_toolbar.SetToolLongHelp(
            ID_GENERATE_AND_PLACE_ORDER,
            "Generate files and Place Order"
        )

        self.upper_toolbar.AddSeparator()

        self.rotation_button = self.upper_toolbar.AddTool(
            ID_ROTATIONS,
            "",
            loadBitmapScaled("nextpcb-rotations.png", self.scale_factor),
            "Rotations"
            #"Manage part rotations",
        )

        # self.mapping_button = self.upper_toolbar.AddTool(
            # ID_MAPPINGS,
            # "",
            # loadBitmapScaled("nextpcb-mapping.png", self.scale_factor),
            # "Mapping"
            # "Import or export part mappings of footprint and MPN",
        # )

        self.settings_button = self.upper_toolbar.AddTool(
            ID_SETTINGS,
            "",
            loadBitmapScaled("nextpcb-setting.png", self.scale_factor),
            "Settings",
        )

        self.upper_toolbar.Realize()

        self.Bind(wx.EVT_COMBOBOX, self.group_parts, self.cb_group_strategy)
        self.Bind(wx.EVT_TOOL, self.auto_match_parts, self.auto_match_button)
        self.Bind(wx.EVT_BUTTON, self.generate_fabrication_data, self.generate_button)
        self.Bind(wx.EVT_BUTTON, self.generate_data_place_order, self.generate_place_order_button)
        self.Bind(wx.EVT_TOOL, self.manage_rotations, self.rotation_button)
        #self.Bind(wx.EVT_TOOL, self.manage_mappings, self.mapping_button)
        #self.Bind(wx.EVT_TOOL, self.update_library, self.download_button)
        self.Bind(wx.EVT_TOOL, self.manage_settings, self.settings_button)

        # ---------------------------------------------------------------------
        # ------------------ down toolbar List --------------------------
        # ---------------------------------------------------------------------

        self.down_toolbar = wx.ToolBar(
            self,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.Size(1400, -1),
            wx.TB_HORIZONTAL | wx.TB_TEXT | wx.TB_HORZ_LAYOUT | wx.TB_NODIVIDER
        )
        #self.down_toolbar.AddStretchableSpace()
        self.select_part_button = wx.Button(
            self.down_toolbar,
            ID_MANUAL_MATCH,
            " Manual Match "
        )
        self.down_toolbar.AddSeparator()

        self.down_toolbar.SetToolLongHelp(
            ID_MANUAL_MATCH,
            "Assign MPN number to a part by manual"
        )
        self.select_part_button.SetDefault()
        self.down_toolbar.AddControl(self.select_part_button)

        self.down_toolbar.AddSeparator()
        
        self.remove_part_button = wx.Button(
            self.down_toolbar,
            ID_REMOVE_PART,
            " Remove Assigned MPN "
        )
        self.remove_part_button.SetDefault()
        self.down_toolbar.AddControl(self.remove_part_button)
        self.down_toolbar.AddSeparator()

        # self.save_all_button = wx.Button(
            # self.down_toolbar,
            # ID_SAVE_MAPPINGS,
            # " Save Mappings "
        # )
        # self.save_all_button.SetDefault()
        #self.down_toolbar.AddControl(self.save_all_button)
        self.down_toolbar.SetFocus()
        self.down_toolbar.AddStretchableSpace()
        
        self.down_toolbar.Realize()

        self.Bind(wx.EVT_BUTTON, self.select_part, self.select_part_button)
        self.Bind(wx.EVT_BUTTON, self.remove_part, self.remove_part_button)
        # self.Bind(wx.EVT_BUTTON, self.save_all_mappings, self.save_all_button)
        #self.Bind(wx.EVT_TOOL, self.export_to_schematic, self.export_schematic_button)


        # ---------------------------------------------------------------------
        # ----------------------- Footprint List ------------------------------
        # ---------------------------------------------------------------------
        table_sizer = wx.BoxSizer(wx.VERTICAL)
        table_sizer.SetMinSize(HighResWxSize(self.window, wx.Size(-1, 600)))

        self.notebook = wx.Notebook(self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, 0)
        self.first_panel = wx.Panel(self.notebook, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.TAB_TRAVERSAL)
        #self.m_dataViewListCtrl10 = wx.dataview.DataViewListCtrl( self.first_panel, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, 0 )
        self.first_panel.Layout()
        self.notebook.AddPage(self.first_panel, "All", True)
        # grid_sizer1 = wx.GridSizer(0, 1, 0, 0)
        # self.first_panel.SetSizer(grid_sizer1)
        # grid_sizer1.Fit(self.first_panel)
        # self.footprint_list = FootPrintList(self.first_panel, self)
        # grid_sizer1.Add(self.footprint_list, 20, wx.ALL | wx.EXPAND, 5)
        grid_sizer1 = wx.GridSizer(0, 1, 0, 0)
        self.first_panel.SetSizer(grid_sizer1)
        grid_sizer1.Fit(self.first_panel)
        self.fplist_all = FootPrintList(self.first_panel, self)
        grid_sizer1.Add(self.fplist_all, 20, wx.ALL | wx.EXPAND, 5)
        self.selected_page_index = 0

        self.second_panel = wx.Panel(self.notebook, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.TAB_TRAVERSAL)
        self.second_panel.Layout()
        self.notebook.AddPage(self.second_panel, "Unmanaged", False)
        
        
        grid_sizer2 = wx.GridSizer(0, 1, 0, 0)
        grid_sizer2.Fit(self.second_panel)
        self.second_panel.SetSizer(grid_sizer2)
        self.fplist_unmana = FootPrintList(self.second_panel, self)
        grid_sizer2.Add(self.fplist_unmana, 20, wx.ALL | wx.EXPAND, 5)

        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_notebook_page_changed)

        #self.on_notebook_page_changed(wx.EVT_NOTEBOOK_PAGE_CHANGED)
        table_sizer.Add(self.notebook, 20, wx.EXPAND |wx.ALL, 5)

        table_sizer.Add(self.down_toolbar, 1, wx.ALL | wx.EXPAND, 5)
        # ---------------------------------------------------------------------
        # --------------------- Bottom Logbox and Gauge -----------------------
        # ---------------------------------------------------------------------
        self.logbox = wx.TextCtrl(
            self,
            wx.ID_ANY,
            wx.EmptyString,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TE_MULTILINE | wx.TE_READONLY,
        )
        self.logbox.SetMinSize(HighResWxSize(self.window, wx.Size(-1, 150)))
        self.gauge = wx.Gauge(
            self,
            wx.ID_ANY,
            100,
            wx.DefaultPosition,
            HighResWxSize(self.window, wx.Size(100, -1)),
            wx.GA_HORIZONTAL,
        )
        self.gauge.SetValue(0)
        self.gauge.SetMinSize(HighResWxSize(self.window, wx.Size(-1, 5)))

        # ---------------------------------------------------------------------
        # ---------------------- Main Layout Sizer ----------------------------
        # ---------------------------------------------------------------------

        self.SetSizeHints(HighResWxSize(self.window, wx.Size(1000, -1)), wx.DefaultSize)
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(self.upper_toolbar, 0, wx.ALL | wx.EXPAND, 5)
        layout.Add(table_sizer, 21, wx.ALL | wx.EXPAND, 5)
        layout.Add(self.logbox, 0, wx.ALL | wx.EXPAND, 5)
        layout.Add(self.gauge, 0, wx.ALL | wx.EXPAND, 5)

        self.SetSizer(layout)
        self.Layout()
        self.Centre(wx.BOTH)

        # ---------------------------------------------------------------------
        # ------------------------ Custom Events ------------------------------
        # ---------------------------------------------------------------------

        self.Bind(EVT_RESET_GAUGE_EVENT, self.reset_gauge)
        self.Bind(EVT_UPDATE_GAUGE_EVENT, self.update_gauge)
        self.Bind(EVT_MESSAGE_EVENT, self.display_message)
        self.Bind(EVT_ASSIGN_PARTS_EVENT, self.assign_parts)
        self.Bind(EVT_POPULATE_FOOTPRINT_LIST_EVENT, self.populate_footprint_list)
        self.Bind(EVT_UPDATE_SETTING, self.update_settings)

        self.enable_toolbar_buttons(False)

        self.init_logger()
        #self.init_library()
        self.on_notebook_page_changed(None)
        self.init_fabrication()
        self.init_store()
        # if self.library.state == LibraryState.UPDATE_NEEDED:
            # self.library.update()
        # else:
            
        #self.library.create_mapping_table()


    def on_notebook_page_changed(self, e):
        self.selected_page_index = self.notebook.GetSelection()
        if self.selected_page_index == 0:
            self.footprint_list = self.fplist_all
            # grid_sizer1 = wx.GridSizer(0, 1, 0, 0)
            # self.first_panel.SetSizer(grid_sizer1)
            # grid_sizer1.Fit(self.first_panel)
            # self.footprint_list = FootPrintList(self.first_panel, self)
            # grid_sizer1.Add(self.footprint_list, 20, wx.ALL | wx.EXPAND, 5)
        elif self.selected_page_index == 1:
            self.footprint_list = self.fplist_unmana
            # grid_sizer2 = wx.GridSizer(0, 1, 0, 0)
            # grid_sizer2.Fit(self.second_panel)
            # self.second_panel.SetSizer(grid_sizer2)
            # self.footprint_list = FootPrintList(self.second_panel, self)
            # grid_sizer2.Add(self.footprint_list, 20, wx.ALL | wx.EXPAND, 5)

        # if self.library.state == LibraryState.INITIALIZED:
        self.populate_footprint_list()  
            

    def quit_dialog(self, e):
        """Destroy dialog on close"""
        self.Destroy()
        self.EndModal(0)

    def init_library(self):
        """Initialize the parts library"""
        self.library = Library(self)

    def init_store(self):
        """Initialize the store of part assignments"""
        self.store = Store(self, self.project_path)
        #if self.library.state == LibraryState.INITIALIZED:
        self.populate_footprint_list()

    def init_fabrication(self):
        """Initialize the fabrication"""
        self.fabrication = Fabrication(self)

    def reset_gauge(self, e):
        """Initialize the gauge."""
        self.gauge.SetRange(100)
        self.gauge.SetValue(0)

    def update_gauge(self, e):
        """Update the gauge"""
        self.gauge.SetValue(int(e.value))

    def group_parts(self, e):
        """ """
        if self.group_strategy != self.cb_group_strategy.GetSelection():
            self.group_strategy = self.cb_group_strategy.GetSelection()
            self.populate_footprint_list()
        

    def get_display_parts(self):
        """ """
        parts = []
        if self.group_strategy == 0:
            parts = self.store.read_all()
        elif self.group_strategy == 1:
            parts = self.store.read_parts_by_group_value_footprint()
            # self.logger.debug(parts)
        return parts

    def auto_match_parts(self, e):
        self.upper_toolbar.EnableTool(ID_AUTO_MATCH, False)
        try:
            wx.BeginBusyCursor()
            #get unmanaged part from UI
            unmanaged_parts = self.get_unmanaged_parts_from_list()
            #send request, parse rsp

            #wx.MessageBox(f"unmanaged_parts:{unmanaged_parts}", "Help", style=wx.ICON_INFORMATION)
            # start = 0
            # batch_size = 5
            # while start < len(unmanaged_parts):
                # batch_parts = unmanaged_parts[start:start+batch_size]
            # unmanaged_parts = unmanaged_parts[:10]
                # 
                # 
                # 
                # start += batch_size

            thread = threading.Thread(target=self.bom_match_api_request(unmanaged_parts))
            thread.start()
            thread.join()
            
            self.update_db_after_match()

            self.populate_footprint_list()
            wx.MessageBox(
                "Auto match finished.Some parts might match failed.\nYou can try it again or match by manual.", 
                "Info",
                style=wx.ICON_INFORMATION
            )
        finally:
            wx.EndBusyCursor()
            self.upper_toolbar.EnableTool(ID_AUTO_MATCH, True)

    def get_unmanaged_parts_from_list(self):
        rows = []
        parts = self.store.read_parts_by_group_value_footprint()
        #wx.MessageBox(f"self.footprint_list.counts:{self.footprint_list.GetItemCount()}", "Help", style=wx.ICON_INFORMATION)
        for part in parts:
            ref = part[0]
            val = part[1]
            fp = part[2]
            mpn = part[3]
            if not mpn:
                row = [ref, val, fp]
                rows.append(row)
        return rows

    def bom_match_api_request(self, unmanaged_parts):
        
        start = 0
        batch_size = 20
        match_parts = {}
        self.matched_list = []
        while start < len(unmanaged_parts):
            #wx.MessageBox(f"len(unmanaged_parts):{len(unmanaged_parts)}", "Help", style=wx.ICON_INFORMATION)
            batch_parts = unmanaged_parts[start:start+batch_size]
            #wx.MessageBox(f"batch_parts:{batch_parts}", "Help", style=wx.ICON_INFORMATION)
            #wx.MessageBox(f"before_start:{start}", "Help", style=wx.ICON_INFORMATION)
            start += batch_size
            #wx.MessageBox(f"after_start:{start}", "Help", style=wx.ICON_INFORMATION)
            # data = {
                # "Content-Type": "application/json",
                # "number": 1,
                # "system": "hqchip",
                # "vendor": "hqchip",
                # "type": 2,
                # "loss": 1,
                # "match_model": 2,
                # "search_order": "goods_name",
                # "service_type": 3,
                # "type": ["localtion", "goods_other_name", "encap"],
                # "list": batch_parts
            # }
            data = {
                "type": 1,
                "url": "/v3/match?number=1&system=hqchip&vendor=hqchip&loss=1&match_model=2&search_order=goods_name&service_type=3",
                "params": {
                    "type": ["localtion","goods_other_name","encap"],
                    "list": batch_parts
                }
            }
            body_json = json.dumps(data, indent=None, ensure_ascii=False)
            #wx.MessageBox(f"body_json:{body_json}", "Help", style=wx.ICON_INFORMATION)
            response = requests.post(
                "https://edaapi.nextpcb.com/edapluginsapi/bom/v3/match/",
                data=body_json
            )

            if response.status_code != 200:
                wx.MessageBox(
                    f"non-OK HTTP response.status code:{response.status_code}", 
                    "Error",
                    style=wx.ICON_ERROR
                )
                #wx.CallAfter(wx.EndBusyCursor)
                continue
            
            rsp_data = response.json()
            Print(self, str(rsp_data)).ShowModal()
            #wx.MessageBox(f"response.json():{data}", "Help", style=wx.ICON_INFORMATION)
            #wx.MessageBox(f"info:{rsp_data.get('info')}", "Help", style=wx.ICON_INFORMATION)
            if rsp_data.get("info") != "SUCCESS":
                # wx.MessageBox(
                    # "Some parts match failed.Skip them and continue to match", 
                    # "Info",
                    # style=wx.ICON_INFORMATION
                # )
                #wx.CallAfter(wx.EndBusyCursor)
                continue
            
            if not rsp_data.get("data", {}).get("match", {}):
                #wx.CallAfter(wx.EndBusyCursor)
                # unmatch
                continue
            match_parts = rsp_data.get("data", {}).get("match", {})
            
            key_params = [
                "ModelName",
                "BrandName",
                "Desc",
                "GoodsId"
            ]

            for part_info in match_parts.values():
                #wx.MessageBox(f"part_info:{part_info}", "Help", style=wx.ICON_INFORMATION)
                temp_list = []
                temp_dict = {}
                for k in key_params:
                    temp_list.append(part_info.get("match", {}).get(k, ""))
                    
                #wx.MessageBox(f"temp_list:{temp_list}", "Help", style=wx.ICON_INFORMATION)
                #wx.MessageBox(f"part_info.get('0'):{part_info.get('0')}", "Help", style=wx.ICON_INFORMATION)
                temp_dict[part_info.get("0")] = temp_list
                #wx.MessageBox(f"temp_dict:{temp_dict}", "Help", style=wx.ICON_INFORMATION)

                self.matched_list.append(temp_dict)
            #wx.MessageBox(f"self.matched_list:{self.matched_list}", "Help", style=wx.ICON_INFORMATION)

            wx.CallAfter(self.update_db_after_match)
            wx.CallAfter(self.populate_footprint_list)
            #wx.CallAfter(wx.EndBusyCursor)
        
    def update_db_after_match(self):
        #wx.MessageBox(f"db_self.matched_list:{self.matched_list}", "Help", style=wx.ICON_INFORMATION)
        if self.matched_list:
            for i in self.matched_list:
                #wx.MessageBox(f"i:{i}", "Help", style=wx.ICON_INFORMATION)
                references = list(i.keys())[0]
                #wx.MessageBox(f"references:{references}", "Help", style=wx.ICON_INFORMATION)
                partinfo_list = i.get(references, [])
                
                #wx.MessageBox(f"partinfo_list:{partinfo_list}", "Help", style=wx.ICON_INFORMATION)
                for reference in references.split(","):
                    #wx.MessageBox(f"reference:{reference}", "Help", style=wx.ICON_INFORMATION)
                    #wx.MessageBox(f"partinfo_list[0]:{partinfo_list[0]}", "Help", style=wx.ICON_INFORMATION)
                    self.store.set_lcsc(reference, partinfo_list[0])
                    self.store.set_manufacturer(reference, partinfo_list[1])
                    self.store.set_description(reference, partinfo_list[2])
                    self.store.set_stock_id(reference, partinfo_list[3])

    def generate_fabrication_data(self, e):
        """Generate fabrication data."""
        self.fabrication.fill_zones()
        #wx.MessageBox("fillzones:", "Help", style=wx.ICON_INFORMATION)
        # layer_selection = self.layer_selection.GetSelection()
        # if layer_selection != 0:
            # layer_count = int(self.layer_selection.GetString(layer_selection)[:1])
        # else:
            # layer_count = None
        self.fabrication.generate_geber(None)
        self.fabrication.generate_excellon()
        #wx.MessageBox("generate excellon:", "Help", style=wx.ICON_INFORMATION)
        self.fabrication.zip_gerber_excellon()
        #wx.MessageBox("zip:", "Help", style=wx.ICON_INFORMATION)
        self.fabrication.generate_cpl()
        #wx.MessageBox("CPL:", "Help", style=wx.ICON_INFORMATION)
        self.fabrication.generate_bom()
        #wx.MessageBox("BOM:", "Help", style=wx.ICON_INFORMATION)


    def generate_data_place_order(self, e):
        self.generate_fabrication_data(e)
        self.place_order_request()
        

    def place_order_request(self):
        zipname = f"GERBER-{self.fabrication.filename.split('.')[0]}.zip"
        zipfile = os.path.join(self.fabrication.outputdir, zipname)
        files = {'file': open(zipfile, 'rb')}
        upload_url = "https://www.nextpcb.com/Upfile/kiCadUpFile"
        data = {
            "type": "pcbfile",
            "bwidth": ToMM(GetBoard().GetBoardEdgesBoundingBox().GetWidth()),
            "blength": ToMM(GetBoard().GetBoardEdgesBoundingBox().GetHeight()),
            "blayer": GetBoard().GetCopperLayerCount() if hasattr(GetBoard(), 'GetCopperLayerCount') else ""
        }
        rsp = requests.post(
            upload_url,
            files=files,
            data=data
        )
        urls = json.loads(rsp.content)
        webbrowser.open(urls['redirect'])

    def assign_parts(self, e):
        """Assign a selected LCSC number to parts"""
        #wx.MessageBox(f"e.references:{e.references}", "Help", style=wx.ICON_INFORMATION)
        for reference in e.references:
            #wx.MessageBox(f"references:{reference}", "Help", style=wx.ICON_INFORMATION)
            self.store.set_lcsc(reference, e.mpn)
            self.store.set_manufacturer(reference, e.manufacturer)
            self.store.set_description(reference, e.description)
            self.store.set_stock_id(reference, e.stock_id)
            #wx.MessageBox(f"e.stock_id:{e.stock_id}", "Help", style=wx.ICON_INFORMATION)
        
        self.populate_footprint_list()

    def display_message(self, e):
        """Dispaly a message with the data from the event"""
        styles = {
            "info": wx.ICON_INFORMATION,
            "warning": wx.ICON_WARNING,
            "error": wx.ICON_ERROR,
        }
        wx.MessageBox(e.text, e.title, style=styles.get(e.style, wx.ICON_INFORMATION))

    def populate_footprint_list(self, e=None):
        """Populate/Refresh list of footprints."""
        if not self.store:
            self.init_store()
        self.footprint_list.DeleteAllItems()
        # icons = {
            # 0: wx.dataview.DataViewIconText(
                # "",
                # loadIconScaled(
                    # "nextpcb-checkced.png",
                    # self.scale_factor,
                # ),
            # ),
            # 1: wx.dataview.DataViewIconText(
                # "",
                # loadIconScaled(
                    # "nextpcb-uncheck.png",
                    # self.scale_factor,
                # ),
            # ),
            # 2: wx.dataview.DataViewIconText(
                # "",
                # loadIconScaled(
                    # "nextpcb-disablecheck.png",
                    # self.scale_factor,
                # ),
            # ),
        # }
        toogles_dict = {
            0: False,
            1: True,
            '0': False,
            '1': True,
        }
        numbers = []
        parts = []
        display_parts = self.get_display_parts()
        for part in display_parts:
            fp = get_footprint_by_ref(GetBoard(), (part[0].split(","))[0])[0]
            if part[3] and part[3] not in numbers:
                numbers.append(part[3])
            if ',' in part[0]:
                part[4] = (part[4].split(","))[0]
                part[5] = (part[5].split(","))[0]
                part[6] = 0 if '0' in part[6].split(",") else 1
                part[7] = 0 if '0' in part[7].split(",") else 1
                part[8] = ''
                part[9] = "T/B" if ('top' in part[9]) and ('bottom' in part[9]) else (part[9].split(','))[0]
            part[6] = toogles_dict.get(part[6], toogles_dict.get(1))
            part[7] = toogles_dict.get(part[7], toogles_dict.get(1))
            if ',' not in part[0]:
                side = "top" if fp.GetLayer() == 0 else "bottom"
                self.store.set_part_side(part[0], side)
                part[9] = side
            part.insert(10, "")
            parts.append(part)
        #details = self.library.get_part_details(numbers)
        #corrections = self.library.get_all_correction_data()
        # find rotation correction values
        for idx, part in enumerate(parts, start=1):
            # detail = list(filter(lambda x: x[0] == part[3], details))
            # if detail:
                # part[4] = detail[0][2]
                # part[5] = detail[0][1]
            ##First check if the part name mathes
            # for regex, correction in corrections:
                # if re.search(regex, str(part[1])):
                    # part[8] = correction
                    # break
            ##If there was no match for the part name, check if the package matches
            # if part[8] == "":
                # for regex, correction in corrections:
                    # if re.search(regex, str(part[2])):
                        # part[8] = correction
                        # break
            
            part.insert(0, f'{idx}')
            if self.selected_page_index == 1 and part[4]:
                continue
            self.footprint_list.AppendItem(part)

    def OnSortFootprintList(self, e):
        """Set order_by to the clicked column and trigger list refresh."""
        self.store.set_order_by(e.GetColumn())
        self.populate_footprint_list()

    def OnBomHide(self, e):
        """Hide all parts from the list that have 'in BOM' set to No."""
        self.hide_bom_parts = not self.hide_bom_parts
        if self.hide_bom_parts:
            self.hide_bom_button.SetNormalBitmap(
                loadBitmapScaled(
                    "",
                    self.scale_factor,
                )
            )
            self.hide_bom_button.SetNormalBitmap(
                loadBitmapScaled(
                    "mdi-eye-outline.png",
                    self.scale_factor,
                )
            )
            self.hide_bom_button.SetLabel("Show excluded BOM")
        else:
            self.hide_bom_button.SetNormalBitmap(
                loadBitmapScaled(
                    "",
                    self.scale_factor,
                )
            )
            self.hide_bom_button.SetNormalBitmap(
                loadBitmapScaled(
                    "mdi-eye-off-outline.png",
                    self.scale_factor,
                )
            )
            self.hide_bom_button.SetLabel("Hide excluded BOM")
        self.populate_footprint_list()

    def OnPosHide(self, e):
        """Hide all parts from the list that have 'in pos' set to No."""
        self.hide_pos_parts = not self.hide_pos_parts
        if self.hide_pos_parts:
            self.hide_pos_button.SetNormalBitmap(
                loadBitmapScaled(
                    "",
                    self.scale_factor,
                )
            )
            self.hide_pos_button.SetNormalBitmap(
                loadBitmapScaled(
                    "mdi-eye-outline.png",
                    self.scale_factor,
                )
            )
            self.hide_pos_button.SetLabel("Show excluded POS")
        else:
            self.hide_pos_button.SetNormalBitmap(
                loadBitmapScaled(
                    "",
                    self.scale_factor,
                )
            )
            self.hide_pos_button.SetNormalBitmap(
                loadBitmapScaled(
                    "mdi-eye-off-outline.png",
                    self.scale_factor,
                )
            )
            self.hide_pos_button.SetLabel("Hide excluded POS")
        self.populate_footprint_list()

    def OnFootprintSelected(self, e):
        """Enable the toolbar buttons when a selection was made."""
        self.enable_toolbar_buttons(self.footprint_list.GetSelectedItemsCount() > 0)

    def enable_all_buttons(self, state):
        """Control state of all the buttons"""
        self.enable_top_buttons(state)
        self.enable_toolbar_buttons(state)

    def enable_top_buttons(self, state):
        """Control the state of all the buttons in the top section"""
        for button in (
            ID_GROUP,
            ID_AUTO_MATCH,
            ID_GENERATE,
            ID_GENERATE_AND_PLACE_ORDER,
            ID_ROTATIONS,
            ID_MAPPINGS,
            ID_SETTINGS
            ):
            self.upper_toolbar.EnableTool(button, state)

    def enable_toolbar_buttons(self, state):
        """Control the state of all the buttons in toolbar on the right side"""
        for button in (
            ID_MANUAL_MATCH,
            ID_REMOVE_PART,
            ID_SELECT_SAME_PARTS,
            ID_PART_DETAILS,
            ID_TOGGLE_BOM,
            ID_TOGGLE_POS
            #ID_SAVE_MAPPINGS
        ):
            self.down_toolbar.EnableTool(button, state)

    # def toggle_bom_pos(self, e):
        # """Toggle the exclude from BOM/POS attribute of a footprint."""
        # selected_rows = []
        # for item in self.footprint_list.GetSelections():
            # row = self.footprint_list.ItemToRow(item)
            # selected_rows.append(row)
            # ref = self.footprint_list.GetTextValue(row, 0)
            # fp = get_footprint_by_ref(GetBoard(), ref)[0]
            # bom = toggle_exclude_from_bom(fp)
            # pos = toggle_exclude_from_pos(fp)
            # self.store.set_bom(ref, bom)
            # self.store.set_pos(ref, pos)
        # self.populate_footprint_list()
        # for row in selected_rows:
            # self.footprint_list.SelectRow(row)

    def toggle_bom(self, e):
        """Toggle the exclude from BOM attribute of a footprint."""
        selected_rows = []
        #self.logger.debug("toggle bom")
        for item in self.footprint_list.GetSelections():
            row = self.footprint_list.ItemToRow(item)
            selected_rows.append(row)
            refs = self.footprint_list.GetTextValue(row, 1).split(",")
            for ref in refs:
                #fp = get_footprint_by_ref(GetBoard(), ref)[0]
                bom = self.footprint_list.GetValue(row, 7)
                #wx.MessageBox(f"stockID:{bom}", "Help", style=wx.ICON_INFORMATION)
                self.store.set_bom(ref, bom)
                
        self.populate_footprint_list()
        for row in selected_rows:
            self.footprint_list.SelectRow(row)

    def toggle_pos(self, e):
        """Toggle the exclude from POS attribute of a footprint."""
        selected_rows = []
        #self.logger.debug("toggle pos")
        for item in self.footprint_list.GetSelections():
            row = self.footprint_list.ItemToRow(item)
            selected_rows.append(row)
            refs = self.footprint_list.GetTextValue(row, 1).split(",")
            for ref in refs:
                #fp = get_footprint_by_ref(GetBoard(), ref)[0]
                pos = self.footprint_list.GetValue(row, 8)
                self.store.set_pos(ref, pos)
        self.populate_footprint_list()
        for row in selected_rows:
            self.footprint_list.SelectRow(row)

    def remove_part(self, e):
        """Remove an assigned a LCSC Part number to a footprint."""
        for item in self.footprint_list.GetSelections():
            row = self.footprint_list.ItemToRow(item)
            ref = self.footprint_list.GetTextValue(row, 1)
            mpn = self.footprint_list.GetTextValue(row, 4)
            if mpn:
                for iter_ref in ref.split(","):
                    if iter_ref:
                        #get_footprint_by_ref(GetBoard(), iter_ref)[0]
                        self.store.set_lcsc(iter_ref, "")
                        self.store.set_manufacturer(iter_ref, "")
                        self.store.set_description(iter_ref, "")
                        self.store.set_bom(iter_ref, True)
                        self.store.set_pos(iter_ref, True)
                        self.store.set_stock_id(iter_ref, 0)   
        self.populate_footprint_list()

    def select_alike(self, e):
        """Select all parts that have the same value and footprint."""
        num_sel = (
            self.footprint_list.GetSelectedItemsCount()
        )  # could have selected more than 1 item (by mistake?)
        if num_sel == 1:
            item = self.footprint_list.GetSelection()
        else:
            self.logger.warning("Select only one component, please.")
            return
        row = self.footprint_list.ItemToRow(item)
        ref = self.footprint_list.GetValue(row, 1)
        part = self.store.get_part(ref)
        for r in range(self.footprint_list.GetItemCount()):
            value = self.footprint_list.GetValue(r, 2)
            fp = self.footprint_list.GetValue(r, 3)
            if part[1] == value and part[2] == fp:
                self.footprint_list.SelectRow(r)

    def get_part_details(self, e):
        """Fetch part details from NextPCB and show them one after another each in a modal."""
        item = self.footprint_list.GetSelection()
        row = self.footprint_list.ItemToRow(item)
        mpn = self.footprint_list.GetTextValue(row, 4)
        if not mpn:
            return
        else:
            ref = self.footprint_list.GetTextValue(row, 1).split(",")[0]
            #wx.MessageBox(f"ref:{ref}", "Help", style=wx.ICON_INFORMATION)
            stock_id = self.store.get_stock_id(ref)
            #wx.MessageBox(f"stockID:{stock_id}", "Help", style=wx.ICON_INFORMATION)
            self.show_part_details_dialog(stock_id)

    def get_column_by_name(self, column_title_to_find):
        """Lookup a column in our main footprint table by matching its title"""
        for col in self.footprint_list.Columns:
            if col.Title == column_title_to_find:
                return col
        return None

    def get_column_position_by_name(self, column_title_to_find):
        """Lookup the index of a column in our main footprint table by matching its title"""
        col = self.get_column_by_name(column_title_to_find)
        if not col:
            return -1
        return self.footprint_list.GetColumnPosition(col)

    def get_selected_part_id_from_gui(self):
        """Get a list of LCSC part#s currently selected"""
        lcsc_ids_selected = []
        for item in self.footprint_list.GetSelections():
            row = self.footprint_list.ItemToRow(item)
            if row == -1:
                continue

            lcsc_id = self.get_row_item_in_column(row, "MPN")
            lcsc_ids_selected.append(lcsc_id)

        return lcsc_ids_selected

    def get_row_item_in_column(self, row, column_title):
        return self.footprint_list.GetTextValue(
            row, self.get_column_position_by_name(column_title)
        )

    def show_part_details_dialog(self, stockID):
        if stockID != "":
            #wx.MessageBox(f"stockID:{stockID}", "Help", style=wx.ICON_INFORMATION)
            try:
                wx.BeginBusyCursor()
                #wx.MessageBox(f"stockID:{stockID}", "Help", style=wx.ICON_INFORMATION)
                PartDetailsDialog(self, int(stockID)).ShowModal()
            finally:
                wx.EndBusyCursor()
        else:
            wx.MessageBox(
                "Failed to get part stockID from NextPCB\r\n",
                "Error",
                style=wx.ICON_ERROR,
            )
        # wx.BeginBusyCursor()
        # try:
            # self.logger.info(f"Opening PartDetailsDialog window for part with value: '{part} (this should be "
                            # f"an LCSC identifier)'")
            # dialog = PartDetailsDialog(self, stockID)
            # dialog.ShowModal()
        # finally:
            # wx.EndBusyCursor()

    def update_library(self, e=None):
        """Update the library from the JLCPCB CSV file."""
        self.library.update()

    def manage_rotations(self, e=None):
        """Manage rotation corrections."""
        RotationManagerDialog(self, "").ShowModal()

    def manage_mappings(self, e=None):
        """Manage footprint mappings."""
        PartMapperManagerDialog(self).ShowModal()

    def manage_settings(self, e=None):
        """Manage settings."""
        SettingsDialog(self).ShowModal()

    def update_settings(self, e):
        """Update the settings on change"""
        if e.section not in self.settings:
            self.settings[e.section] = {}
        self.settings[e.section][e.setting] = e.value
        self.save_settings()

    def load_settings(self):
        """Load settings from settings.json"""
        with open(os.path.join(PLUGIN_PATH, "settings.json")) as j:
            self.settings = json.load(j)

    def save_settings(self):
        """Save settings to settings.json"""
        with open(os.path.join(PLUGIN_PATH, "settings.json"), "w") as j:
            json.dump(self.settings, j)

    def calculate_costs(self, e):
        """Hopefully we will be able to calculate the part costs in the future."""
        pass

    def select_part(self, e):
        """Select a part from the library and assign it to the selected footprint(s)."""
        selection = {}
        for item in self.footprint_list.GetSelections():
            row = self.footprint_list.ItemToRow(item)
            reference = (self.footprint_list.GetValue(row, 1).split(","))[0]
            #self.logger.debug(f"reference, {reference}")
            value = self.footprint_list.GetValue(row, 2)
            fp = self.footprint_list.GetValue(row, 3)
            MPN = self.footprint_list.GetValue(row, 4)
            Manufacturer = self.footprint_list.GetValue(row, 5)
            selection[reference] = MPN + "," + Manufacturer + "," + value + "," + fp
        # self.logger.debug(f"Create SQLite table for rotations, {selection}")
        try:
            wx.BeginBusyCursor()
            PartSelectorDialog(self, selection).ShowModal()
        finally:
            wx.EndBusyCursor()

    def copy_part_lcsc(self, e):
        """Fetch part details from LCSC and show them in a modal."""
        # wx.MessageBox("copyslot", "Help", style=wx.ICON_INFORMATION)
        # if self.footprint_list.GetSelections() > 1:
            # return
        
        item = self.footprint_list.GetSelection()
        row = self.footprint_list.ItemToRow(item)
        if row == -1:
            return
        part = ""
        part += str(self.footprint_list.GetTextValue(row, 4)) + '\n'
        part += str(self.footprint_list.GetTextValue(row, 5)) + '\n'
        part += str(self.footprint_list.GetTextValue(row, 6)) + '\n'
        ref = self.footprint_list.GetTextValue(row, 1).split(",")[0]
        part += str(self.store.get_stock_id(ref))

        #wx.MessageBox(f"copy text part:{part}", "Help", style=wx.ICON_INFORMATION)
        
        if part != "":
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(part))
                wx.TheClipboard.Close()

    def paste_part_lcsc(self, e):
        #wx.MessageBox("copyslot", "Help", style=wx.ICON_INFORMATION)
        text_data = wx.TextDataObject()
        if wx.TheClipboard.Open():
            success = wx.TheClipboard.GetData(text_data)
            wx.TheClipboard.Close()
        if success:
            lines = text_data.GetText().split('\n')
            #wx.MessageBox(f"lines:{lines}", "Help", style=wx.ICON_INFORMATION)
            mpn = lines[0]
            manufacturer = lines[1]
            des = lines[2]
            stock_id = lines[3]

            if mpn == "":
                return
            item = self.footprint_list.GetSelection()
            row = self.footprint_list.ItemToRow(item)
            references = self.footprint_list.GetTextValue(row, 1)
            for ref in references.split(","):
                self.store.set_lcsc(ref, mpn)
                self.store.set_manufacturer(ref, manufacturer)
                self.store.set_description(ref, des)
                self.store.set_stock_id(ref, stock_id)
            
        self.populate_footprint_list()

    def add_part_rot(self, e):
        for item in self.footprint_list.GetSelections():
            row = self.footprint_list.ItemToRow(item)
            if row == -1:
                return
            if e.GetId() == ID_CONTEXT_MENU_ADD_ROT_BY_PACKAGE:
                package = self.footprint_list.GetTextValue(row, 2)
                if package != "":
                    RotationManagerDialog(self, "^" + re.escape(package)).ShowModal()
            elif e.GetId() == ID_CONTEXT_MENU_ADD_ROT_BY_NAME:
                name = self.footprint_list.GetTextValue(row, 1)
                if name != "":
                    RotationManagerDialog(self, re.escape(name)).ShowModal()

    def save_all_mappings(self, e):
        for r in range(self.footprint_list.GetItemCount()):
            footp = self.footprint_list.GetTextValue(r, 2)
            partval = self.footprint_list.GetTextValue(r, 1)
            lcscpart = self.footprint_list.GetTextValue(r, 3)
            if footp != "" and partval != "" and lcscpart != "":
                if self.library.get_mapping_data(footp, partval):
                    self.library.update_mapping_data(footp, partval, lcscpart)
                else:
                    self.library.insert_mapping_data(footp, partval, lcscpart)
        self.logger.info("All mappings saved")

    def export_to_schematic(self, e):
        """Dialog to select schematics."""
        with wx.FileDialog(
            self,
            "Select Schematics",
            self.project_path,
            self.schematic_name,
            "KiCad V6 Schematics (*.kicad_sch)|*.kicad_sch",
            wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        ) as openFileDialog:
            if openFileDialog.ShowModal() == wx.ID_CANCEL:
                return
            paths = openFileDialog.GetPaths()
            SchematicExport(self).load_schematic(paths)

    def add_foot_mapping(self, e):
        for item in self.footprint_list.GetSelections():
            row = self.footprint_list.ItemToRow(item)
            if row == -1:
                return
            footp = self.footprint_list.GetTextValue(row, 3)
            partval = self.footprint_list.GetTextValue(row, 2)
            lcscpart = self.footprint_list.GetTextValue(row, 4)
            if footp != "" and partval != "" and lcscpart != "":
                if self.library.get_mapping_data(footp, partval):
                    self.library.update_mapping_data(footp, partval, lcscpart)
                else:
                    self.library.insert_mapping_data(footp, partval, lcscpart)

    def search_foot_mapping(self, e):
        for item in self.footprint_list.GetSelections():
            row = self.footprint_list.ItemToRow(item)
            if row == -1:
                return
            footp = self.footprint_list.GetTextValue(row, 3)
            partval = self.footprint_list.GetTextValue(row, 2)
            if footp != "" and partval != "":
                if self.library.get_mapping_data(footp, partval):
                    lcsc = self.library.get_mapping_data(footp, partval)[2]
                    reference = self.footprint_list.GetTextValue(row, 0)
                    self.store.set_lcsc(reference, lcsc)
                    self.logger.info(f"Found {lcsc}")
        self.populate_footprint_list()

    def sanitize_lcsc(self, lcsc_PN):
        m = re.search("C\\d+", lcsc_PN, re.IGNORECASE)
        if m:
            return m.group(0)
        return ""

    def OnRightDown(self, e):
        """Right click context menu for action on parts table."""
        conMenu = wx.Menu()
        copy_lcsc = wx.MenuItem(conMenu, ID_COPY_MPN, "Copy MPN")
        conMenu.Append(copy_lcsc)
        conMenu.Bind(wx.EVT_MENU, self.copy_part_lcsc, copy_lcsc)

        paste_lcsc = wx.MenuItem(conMenu, ID_PASTE_MPN, "Paste MPN")
        conMenu.Append(paste_lcsc)
        conMenu.Bind(wx.EVT_MENU, self.paste_part_lcsc, paste_lcsc)

        manual_match = wx.MenuItem(
            conMenu, ID_MANUAL_MATCH, "Manual Match"
        )
        conMenu.Append(manual_match)
        conMenu.Bind(wx.EVT_MENU, self.select_part, manual_match)

        remove_mpn = wx.MenuItem(
            conMenu, ID_REMOVE_PART, "Remove Assigned MPN"
        )
        conMenu.Append(remove_mpn)
        conMenu.Bind(wx.EVT_MENU, self.remove_part, remove_mpn)

        part_detail = wx.MenuItem(conMenu, ID_PART_DETAILS, "Show Part Details")
        conMenu.Append(part_detail)
        conMenu.Bind(wx.EVT_MENU, self.get_part_details, part_detail)

        item_count = len(self.footprint_list.GetSelections())
        if item_count > 1:
            for menu_item in (
                ID_COPY_MPN,
                ID_PASTE_MPN,
                ID_MANUAL_MATCH,
                ID_PART_DETAILS
                ):
                conMenu.Enable(menu_item, False)
        else:
            item = self.footprint_list.GetSelection()
            row = self.footprint_list.ItemToRow(item)
            if row == -1:
                return
            mpn = self.footprint_list.GetTextValue(row, 4)
            state = False if not mpn else True
            
            for menu_item in (
                ID_COPY_MPN,
                ID_REMOVE_PART,
                ID_PART_DETAILS
                ):
                conMenu.Enable(menu_item, state)
        self.footprint_list.PopupMenu(conMenu)
        conMenu.Destroy()  # destroy to avoid memory leak

    def toggle_update_to_db(self, e):
        col = e.GetColumn()

        if col == 7:
            self.toggle_bom(e)
        elif col == 8:
            self.toggle_pos(e)
        else:
            pass

    def init_logger(self):
        """Initialize logger to log into textbox"""
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        # Log to stderr
        handler1 = logging.StreamHandler(sys.stderr)
        handler1.setLevel(logging.DEBUG)
        # and to our GUI
        handler2 = LogBoxHandler(self.logbox)
        handler2.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(funcName)s -  %(message)s",
            datefmt="%Y.%m.%d %H:%M:%S",
        )
        handler1.setFormatter(formatter)
        handler2.setFormatter(formatter)
        root.addHandler(handler1)
        root.addHandler(handler2)
        self.logger = logging.getLogger(__name__)

    def __del__(self):
        pass


class LogBoxHandler(logging.StreamHandler):
    def __init__(self, textctrl):
        logging.StreamHandler.__init__(self)
        self.textctrl = textctrl

    def emit(self, record):
        """Pokemon exception that hopefully helps getting this working with threads."""
        try:
            msg = self.format(record)
            self.textctrl.WriteText(msg + "\n")
            self.flush()
        except:
            pass


# app = wx.App(0)
# 
# frame = NextPCBTools(None)
# app.SetTopWindow(frame)
# frame.Show()
