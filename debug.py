import wx

class Print(wx.Dialog):	
    def __init__(self, parent, content):
        wx.Dialog.__init__(
		self,
		parent,
		id=wx.ID_ANY,
		title="debug",
		pos=wx.DefaultPosition,
		style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
		)
        self.text_ctrl = wx.TextCtrl(self, value=content, style=wx.TE_MULTILINE)
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.text_ctrl, 1, wx.EXPAND|wx.ALL, 5)
        