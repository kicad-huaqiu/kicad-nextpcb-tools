import logging
import wx
import requests
import threading
import json
from .events import AssignPartsEvent, UpdateSetting
from .helpers import HighResWxSize, loadBitmapScaled
from .partdetails import PartDetailsDialog
from requests.exceptions import Timeout

def ceil(x, y):
    return -(-x // y)

class PartSelectorDialog(wx.Dialog):
    def __init__(self, parent, parts):
        wx.SizerFlags.DisableConsistencyChecks()
        wx.Dialog.__init__(
            self,
            parent,
            id=wx.ID_ANY,
            title="NextPCB Search Online",
            pos=wx.DefaultPosition,
            size=HighResWxSize(parent.window, wx.Size(1400, 800)),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
        )

        self.logger = logging.getLogger(__name__)
        self.parent = parent
        self.parts = parts
        self.MPN_stockID_dict = {}

        self.current_page = 0
        self.total_pages = 0

        part_selection = self.get_existing_selection(parts)
        self.part_info = part_selection.split(",")
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
        # --------------------------- Search bar ------------------------------
        # ---------------------------------------------------------------------

        keyword_label = wx.StaticText(
            self,
            wx.ID_ANY,
            "MPN",
            size=HighResWxSize(parent.window, wx.Size(150, 15)),
        )
        self.mpn_textctrl = wx.TextCtrl(
            self,
            wx.ID_ANY,
            self.part_info[0],
            wx.DefaultPosition,
            HighResWxSize(parent.window, wx.Size(200, 24)),
            wx.TE_PROCESS_ENTER,
        )
        self.mpn_textctrl.SetHint("e.g. 123456")

        manufacturer_label = wx.StaticText(
            self,
            wx.ID_ANY,
            "Manufacturer",
            size=HighResWxSize(parent.window, wx.Size(150, 15)),
        )
        self.manufacturer = wx.TextCtrl(
            self,
            wx.ID_ANY,
            self.part_info[1],
            wx.DefaultPosition,
            HighResWxSize(parent.window, wx.Size(300, 24)),
            wx.TE_PROCESS_ENTER,
        )
        self.manufacturer.SetHint("e.g. Vishay")

        description_label = wx.StaticText(
            self,
            wx.ID_ANY,
            "Description",
            size=HighResWxSize(parent.window, wx.Size(150, 15)),
        )
        self.description = wx.TextCtrl(
            self,
            wx.ID_ANY,
            self.part_info[2],
            wx.DefaultPosition,
            HighResWxSize(parent.window, wx.Size(200, 24)),
            wx.TE_PROCESS_ENTER,
        )
        self.description.SetHint("e.g. 100nF")

        package_label = wx.StaticText(
            self,
            wx.ID_ANY,
            "Package/Footprint",
            size=HighResWxSize(parent.window, wx.Size(150, 15)),
        )
        self.package = wx.TextCtrl(
            self,
            wx.ID_ANY,
            "",
            wx.DefaultPosition,
            HighResWxSize(parent.window, wx.Size(300, 24)),
            wx.TE_PROCESS_ENTER,
        )
        self.package.SetHint("e.g. 0806")

        self.search_button = wx.Button(
            self,
            wx.ID_ANY,
            "Search",
            wx.DefaultPosition,
            HighResWxSize(parent.window, wx.Size(100, 30)),
            0,
        )

        search_sizer_one = wx.BoxSizer(wx.VERTICAL)
        search_sizer_one.Add(keyword_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        search_sizer_one.Add(
            self.mpn_textctrl,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_CENTER_VERTICAL,
            5,
        )

        search_sizer_two = wx.BoxSizer(wx.VERTICAL)
        search_sizer_two.Add(
            manufacturer_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5
        )
        search_sizer_two.Add(
            self.manufacturer,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_CENTER_VERTICAL,
            5,
        )

        search_sizer_three = wx.BoxSizer(wx.VERTICAL)
        search_sizer_three.Add(
            description_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5
        )
        search_sizer_three.Add(
            self.description,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_CENTER_VERTICAL,
            5,
        )

        search_sizer_four = wx.BoxSizer(wx.VERTICAL)
        search_sizer_four.Add(
            package_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5
        )
        search_sizer_four.Add(
            self.package,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_CENTER_VERTICAL,
            5,
        )

        self.search_button.SetBitmap(
            loadBitmapScaled(
                "nextpcb-search.png",
                self.parent.scale_factor,
            )
        )

        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        search_sizer.Add(search_sizer_one, 0, wx.RIGHT, 20)
        search_sizer.Add(search_sizer_two, 0, wx.RIGHT, 20)
        search_sizer.Add(search_sizer_three, 0, wx.RIGHT, 20)
        search_sizer.Add(search_sizer_four, 0, wx.RIGHT, 20)
        search_sizer.AddStretchSpacer()

        search_sizer.Add(
            self.search_button,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_CENTER_VERTICAL,
            5,
        )
        search_sizer.AddStretchSpacer()

        self.mpn_textctrl.Bind(wx.EVT_TEXT_ENTER, self.search)
        self.manufacturer.Bind(wx.EVT_TEXT_ENTER, self.search)
        self.description.Bind(wx.EVT_TEXT_ENTER, self.search)
        self.package.Bind(wx.EVT_TEXT_ENTER, self.search)
        self.search_button.Bind(wx.EVT_BUTTON, self.search)

        # ---------------------------------------------------------------------
        # ------------------------ Result status line -------------------------
        # ---------------------------------------------------------------------

        self.result_count = wx.StaticText(
            self, wx.ID_ANY, "0 Results", wx.DefaultPosition, HighResWxSize(parent.window, wx.Size(-1, 20)),
        )

        result_sizer = wx.BoxSizer(wx.HORIZONTAL)
        result_sizer.Add(self.result_count, 0, wx.LEFT | wx.ALIGN_BOTTOM, 5)

        # ---------------------------------------------------------------------
        # ------------------------- Result Part list --------------------------
        # ---------------------------------------------------------------------

        self.part_list = wx.dataview.DataViewListCtrl(
            self,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            style=wx.dataview.DV_SINGLE,
        )
        self.part_list.AppendTextColumn(
            "index",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(parent.scale_factor * 60),
            align=wx.ALIGN_LEFT,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )

        self.part_list.AppendTextColumn(
            "MPN",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(parent.scale_factor * 150),
            align=wx.ALIGN_LEFT,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.part_list.AppendTextColumn(
            "Manufacturer",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(parent.scale_factor * 300),
            align=wx.ALIGN_LEFT,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.part_list.AppendTextColumn(
            "Description",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(parent.scale_factor * 200),
            align=wx.ALIGN_LEFT,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.part_list.AppendTextColumn(
            "Package/Footprint",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(parent.scale_factor * 300),
            align=wx.ALIGN_LEFT,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.part_list.AppendTextColumn(
            "Price($)",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(parent.scale_factor * 150),
            align=wx.ALIGN_LEFT,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.part_list.AppendTextColumn(
            "Stock",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(parent.scale_factor * 60),
            align=wx.ALIGN_LEFT,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )
        self.part_list.AppendTextColumn(
            "Supplier",
            mode=wx.dataview.DATAVIEW_CELL_INERT,
            width=int(parent.scale_factor * 50),
            align=wx.ALIGN_LEFT,
            flags=wx.dataview.DATAVIEW_COL_RESIZABLE,
        )

        self.part_list.SetMinSize(HighResWxSize(parent.window, wx.Size(1050, 500)))

        self.part_list.Bind(
            wx.dataview.EVT_DATAVIEW_COLUMN_HEADER_CLICK, self.OnSortPartList
        )

        self.part_list.Bind(
            wx.dataview.EVT_DATAVIEW_SELECTION_CHANGED, self.OnPartSelected
        )

        table_sizer = wx.BoxSizer(wx.VERTICAL)
        table_sizer.SetMinSize(HighResWxSize(parent.window, wx.Size(-1, 500)))
        table_sizer.Add(self.part_list, 20, wx.ALL | wx.EXPAND, 5)

        # ---------------------------------------------------------------------
        # ------------------------Previous and Next page -------------------------
        # ---------------------------------------------------------------------
        self.previous_next_panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.HORIZONTAL )

        prev_button = wx.Button(self.previous_next_panel, label = "Previous",size=(70, 26))
        sizer.Add(prev_button, 0, wx.ALL, 5)

        font = wx.Font(14, wx.DEFAULT, wx.FONTSTYLE_NORMAL, wx.NORMAL)
        container = wx.Panel(self.previous_next_panel, size=(50, 24))
        self.page_label = wx.StaticText(container, label="1/20", style=wx.ALIGN_CENTER)
        self.page_label.SetFont(font)
        container_sizer = wx.BoxSizer(wx.VERTICAL)
        container_sizer.AddStretchSpacer(1)  
        container_sizer.Add(self.page_label, 0, wx.ALIGN_CENTER) 
        container.SetSizer(container_sizer)
        sizer.Add(container, 0, wx.ALL, 5)
        next_button = wx.Button(self.previous_next_panel, label="Next",size=(70, 26))
        sizer.Add(next_button, 0, wx.ALL, 5)

        self.previous_next_panel.SetSizer(sizer)
        self.Layout()

        prev_button.Bind(wx.EVT_BUTTON, self.on_prev_page)
        next_button.Bind(wx.EVT_BUTTON, self.on_next_page)
        self.update_page_label()


        # ---------------------------------------------------------------------
        # ------------------------ down toolbar -------------------------
        # ---------------------------------------------------------------------

        self.select_part_button = wx.Button(
            self,
            wx.ID_ANY,
            "Select part",
            wx.DefaultPosition,
            HighResWxSize(parent.window, wx.Size(120, 30)),
            0,
        )
        self.part_details_button = wx.Button(
            self,
            wx.ID_ANY,
            "Show part details",
            wx.DefaultPosition,
            HighResWxSize(parent.window, wx.Size(120, 30)),
            0,
        )

        self.select_part_button.Bind(wx.EVT_BUTTON, self.select_part)
        self.part_details_button.Bind(wx.EVT_BUTTON, self.get_part_details)

        self.select_part_button.SetBitmap(
            loadBitmapScaled(
                "nextpcb-select-part.png",
                self.parent.scale_factor,
            )
        )

        tool_sizer = wx.BoxSizer(wx.HORIZONTAL)
        tool_sizer.AddStretchSpacer()
        tool_sizer.Add(self.previous_next_panel, 0, wx.ALL | wx.ALIGN_BOTTOM | wx.EXPAND, 5)
        tool_sizer.AddStretchSpacer()
        tool_sizer.Add(self.select_part_button, 0, wx.ALL | wx.ALIGN_BOTTOM | wx.EXPAND, 5)
        tool_sizer.Add(self.part_details_button, 0, wx.ALL | wx.ALIGN_BOTTOM | wx.EXPAND, 5)
        table_sizer.Add(tool_sizer, 0, wx.EXPAND, 5)

        # ---------------------------------------------------------------------
        # ------------------------------ Sizers  ------------------------------
        # ---------------------------------------------------------------------

        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(search_sizer, 0, wx.ALL | wx.EXPAND, 5)
        layout.Add(result_sizer, 0, wx.LEFT | wx.EXPAND, 5)
        layout.Add(table_sizer, 20, wx.ALL | wx.EXPAND, 5)

        self.SetSizer(layout)
        self.Layout()
        self.Centre(wx.BOTH)
        self.enable_toolbar_buttons(False)

    def upadate_settings(self, event):
        """Update the settings on change"""
        wx.PostEvent(
            self.parent,
            UpdateSetting(
                section="partselector",
                setting=event.GetEventObject().GetName(),
                value=event.GetEventObject().GetValue(),
            ),
        )

    @staticmethod
    def get_existing_selection(parts):
        """Check if exactly one LCSC part number is amongst the selected parts."""
        s = set(val for val in parts.values())
        return list(s)[0]

    def quit_dialog(self, e):
        self.Destroy()
        self.EndModal(0)

    def OnSortPartList(self, e):
        """Set order_by to the clicked column and trigger list refresh."""
        self.parent.library.set_order_by(e.GetColumn())
        self.search(None)

    def OnPartSelected(self, e):
        """Enable the toolbar buttons when a selection was made."""
        if self.part_list.GetSelectedItemsCount() > 0:
            self.enable_toolbar_buttons(True)
        else:
            self.enable_toolbar_buttons(False)

    def enable_toolbar_buttons(self, state):
        """Control the state of all the buttons in toolbar on the right side"""
        for b in [
            self.select_part_button,
            self.part_details_button,
        ]:
            b.Enable(bool(state))

    def search(self, e):
        """Search the library for parts that meet the search criteria."""
        search_keyword = ""
        for word in [
            self.mpn_textctrl.GetValue(),
            self.manufacturer.GetValue(),
            self.description.GetValue(),
            self.package.GetValue()
        ]:
            if word:
                search_keyword += str(word + " ")
                
        if self.current_page == 0:
            self.current_page = 1 
        body = {
            "keyword": search_keyword,
            "limit": 150,
            "page": self.current_page,
            "supplier": [],
            "supplierSort": []
        }
        
        url = "https://edaapi.nextpcb.com/edapluginsapi/v1/stock/search"
        self.search_button.Disable()
        try:
            threading.Thread(target=self.search_api_request(url, body)).start()
        finally:
            wx.EndBusyCursor()
            self.search_button.Enable()

    def search_api_request(self, url, data):
        wx.CallAfter(wx.BeginBusyCursor)

        headers = {
            "Content-Type": "application/json",
        }
        body_json = json.dumps(data, indent=None, ensure_ascii=False)
        try:
            response = requests.post(
                url,
                headers=headers,
                data=body_json,
                timeout=10
            )
            
        except Timeout:

            self.report_part_search_error("HTTP response timeout")

        if response.status_code != 200:
            self.report_part_search_error("non-OK HTTP response status")
            return
        data = response.json()
        if not data.get("result", {}):
            self.report_part_search_error(
                "returned JSON data does not have expected 'result' attribute"
            )
        if not data.get("result").get("stockList"):
            self.report_part_search_error(
                "returned JSON data does not have expected 'stockList' attribute"
            )
        self.total_num = data.get("result").get("total", 0)
        
        self.search_part_list = data.get("result").get("stockList", [])
        
        wx.CallAfter(self.populate_part_list)
        wx.CallAfter(wx.EndBusyCursor)
        

  
    def update_subcategories(self, e):
        """Update the possible subcategory selection."""
        self.subcategory.Clear()
        if self.category.GetSelection() != wx.NOT_FOUND:
            subcategories = self.parent.library.get_subcategories(
                self.category.GetValue()
            )
            self.subcategory.AppendItems(subcategories)

    def populate_part_list(self):
        """Populate the list with the result of the search."""
        self.part_list.DeleteAllItems()
        self.MPN_stockID_dict.clear()
        if self.search_part_list is None:
            return
        
        self.total_pages = ceil(self.total_num, 100)
        self.update_page_label()
        self.result_count.SetLabel(f"{self.total_num} Results")
        if self.total_num >= 1000:
            self.result_count.SetLabel("1000 Results (limited)")
        else:
            self.result_count.SetLabel(f"{self.total_num} Results")

        parameters = [
            "goodsName",
            "providerName",
            "goodsDesc",
            "encap",
            "stockNumber"
        ]
        self.item_list = []
        for idx, part_info in enumerate(self.search_part_list, start=1):
            part = []
            for k in parameters:
                val = part_info.get(k, "")
                val = "-" if val == "" else val
                part.append(val)
            pricelist = part_info.get("priceStair", [])
            if pricelist:
                stair_num = len(pricelist)
                min_price = (pricelist[stair_num - 1]).get("hkPrice", 0)
            else:
                min_price = 0
            part.insert(4, str(min_price))
            suppliername = part_info.get("supplierName", "")
            suppliername = "-" if suppliername == "" else suppliername
            part.insert(6, suppliername)
            part.insert(0, f'{idx}')
            self.MPN_stockID_dict["".join(part[:4])] = part_info.get("stockId", 0)
            self.part_list.AppendItem(part)


    def select_part(self, e):
        """Save the selected part number and close the modal."""
        item = self.part_list.GetSelection()
        row = self.part_list.ItemToRow(item)
        if row == -1:
            return
        selection = self.part_list.GetValue(row, 1)
        manu = self.part_list.GetValue(row, 2)
        des = self.part_list.GetValue(row, 3)
        key = str(row + 1) + selection + manu + des
        wx.PostEvent(
            self.parent,
            AssignPartsEvent(
                mpn=selection,
                manufacturer=manu,
                description=des,
                references=list(self.parts.keys()),
                stock_id=self.MPN_stockID_dict.get(key, 0)
            ),
        )
        self.EndModal(wx.ID_OK)

    def get_part_details(self, e):
        """Fetch part details from NextPCB API and show them in a modal."""
        item = self.part_list.GetSelection()
        row = self.part_list.ItemToRow(item)
        if row == -1:
            return
        selection = self.part_list.GetValue(row, 1)
        manu = self.part_list.GetValue(row, 2)
        des = self.part_list.GetValue(row, 3)
        key = str(row + 1) + selection + manu + des
        stock_id = self.MPN_stockID_dict.get(key, 0)
        
        if stock_id != "":
            try:
                wx.BeginBusyCursor()
                PartDetailsDialog(self.parent, int(stock_id)).ShowModal()
            finally:
                 wx.EndBusyCursor()
        else:
            wx.MessageBox(
                "Failed to get part stockID from NextPCB\r\n",
                "Error",
                style=wx.ICON_ERROR,
            )

    def help(self, e):
        """Show message box with help instructions"""
        title = "Help"
        text = """
        Use % as wildcard selector. \n
        For example DS24% will match DS2411\n
        %QFP% wil match LQFP-64 as well as TQFP-32\n
        The keyword search box is automatically post- and prefixed with wildcard operators.
        The others are not by default.\n
        The keyword search field is applied to "LCSC Part", "Description", "MFR.Part",
        "Package" and "Manufacturer".\n
        Enter triggers the search the same way the search button does.\n
        The results are limited to 1000.
        """
        wx.MessageBox(text, title, style=wx.ICON_INFORMATION)

    def report_part_search_error(self, reason):
        wx.MessageBox(
            f"Failed to download part detail from the NextPCB API ({reason})\r\n"
            f"We looked for a part named:\r\n{self.part}\r\n[hint: did you fill in the NextPCB field correctly?]",
            "Error",
            style=wx.ICON_ERROR,
        )
        wx.CallAfter(wx.EndBusyCursor)
        wx.CallAfter(self.search_button.Enable())
        return
    

    def on_prev_page(self,event):
        if self.current_page > 1:
            self.current_page -= 1
            self.search(None)
            self.update_page_label()

    def on_next_page(self, event):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.search(None)
            self.update_page_label()        


    def update_page_label(self):
        self.page_label.SetLabel(f"{self.current_page}/{self.total_pages}")