import torch
import torch.nn.functional as F
from torch_geometric_temporal.nn.recurrent import *
from torch_geometric_temporal.nn.attention import *
from torch_geometric.nn import GCNConv
from torch_geometric.nn.models import DeepGCNLayer

''' 
    Helpful module of K stacked GCN layers
'''
class KLayerGCNConv(torch.nn.Module): 
    def __init__(self, 
                 K: int, 
                 in_channels: int,  
                 out_channels: int,
                 node_dim: int,
                 improved: bool = True,
                 cached: bool = False,
                 add_self_loops: bool = True): 
        super().__init__()
        self.convs = []
        for k in range(K): 
            if k==0:
                self.convs.append(GCNConv(in_channels=in_channels,
                                          out_channels=out_channels,
                                          node_dim=node_dim,
                                          improved=improved,
                                          cached=cached,
                                          add_self_loops=add_self_loops).cuda())
            else: 
                self.convs.append(GCNConv(in_channels=out_channels,
                                          out_channels=out_channels,
                                          node_dim=node_dim,
                                          improved=improved,
                                          cached=cached,
                                          add_self_loops=add_self_loops).cuda())
        '''
        Note: saving and loading doesnt work when theres a list like self.convs. 
        So we convert it to nn.sequential. 
        See here: 
            https://discuss.pytorch.org/t/loading-saved-models-gives-inconsistent-results-each-time/36312/24
        '''
        self.convs = torch.nn.Sequential(*self.convs)
    def forward(self, x, edge_index, edge_weight):
        for k in range(len(self.convs)): 
            x = self.convs[k].forward(x, edge_index, edge_weight)
            return x
        
'''
    A GCN-GRU model with dense connection, implemented with pyg.DeepGCNLayer 
'''
class DenseGCNGRU(torch.nn.Module):
    def __init__(
        self,
        in_channels: int,  
        periods: int, 
        batch_size:int, 
        improved: bool = False,
        cached: bool = False,
        add_self_loops: bool = True):
        super().__init__()

        self.in_channels = in_channels  # 2
        self.periods = periods # 20
        self.improved = improved
        self.cached = cached
        self.add_self_loops = add_self_loops
        self.batch_size = batch_size
        self._setup_layers()

    def _setup_layers(self):
        self.densegcn= DeepGCNLayer(conv=KLayerGCNConv(K=3,
                                                       in_channels=self.in_channels,
                                                       out_channels=128,
                                                       node_dim=1,
                                                       improved=self.improved,
                                                       cached=self.cached,
                                                       add_self_loops=self.add_self_loops,
                                                      ),
                                    norm=None,
                                    act=torch.nn.LeakyReLU(),
                                    dropout=0.1, 
                                    block='dense')
        self.gru = torch.nn.GRU(130,64,2,batch_first=True)
        self.fc = torch.nn.Linear(64, self.periods)
        
    def forward(self, 
                X: torch.FloatTensor,
                edge_index: torch.LongTensor, 
                edge_weight: torch.FloatTensor = None,
               ) -> torch.FloatTensor:
        gru_in = torch.zeros(X.shape[0],X.shape[1],X.shape[3],130).to(X.device) # (B,N,T_in,F_out_GCN)
        for t in range(X.shape[3]):
            gcn_out = self.densegcn(X[:, :, :, t], edge_index, edge_weight) # (B, N, Fout)
            gru_in[:,:,t,:] = gcn_out
        gru_in = gru_in.flatten(start_dim=0, end_dim=1) # (B*N, T_in, F_out_GCN)
        gru_out, _ = self.gru(gru_in) # (B*N,T_in,H)
        out = self.fc(gru_out[:,-1,:]) # (B*N, T_out)
        out = out.view(X.shape[0], X.shape[1], self.periods, -1) # (B,N,T_out,1)
        return out.squeeze(dim=3) # (B,N,T_out)

'''
    Simple GRU model (does not use edge_index)
'''
class GRU_only(torch.nn.Module):
    def __init__(
        self,
        in_channels: int,  
        periods: int, 
        batch_size:int, 
        improved: bool = False,
        cached: bool = False,
        add_self_loops: bool = True):
        super().__init__()

        self.in_channels = in_channels  # 2
        self.periods = periods # 12
        self.improved = improved
        self.cached = cached
        self.add_self_loops = add_self_loops
        self.batch_size = batch_size
        self._setup_layers()

    def _setup_layers(self):
        self.gru = torch.nn.GRU(self.in_channels,64,2,batch_first=True)
        self.fc = torch.nn.Linear(64, self.periods)

    def forward( self, 
                X: torch.FloatTensor,
                edge_index: torch.LongTensor = None,  # dummy placeholder
                edge_weight: torch.FloatTensor = None, # dummy placeholder
               ) -> torch.FloatTensor:
        gru_in = torch.reshape(X, (X.shape[0], X.shape[1], self.periods, -1)) #(B,N,2,T)->(B,N,T,2)
        gru_in = gru_in.flatten(start_dim=0, end_dim=1) # (B*N, T, 2)        
        gru_out, _ = self.gru(gru_in) # (B*N,T_in,H)
        out = self.fc(gru_out[:,-1,:]) # (B*N, T_out)
        out = out.view(X.shape[0], X.shape[1], self.periods, -1) # (B,N,T_out,1)
        return out.squeeze(dim=3) # (B,N,T_out)
    
'''
    GCN GRU model without dense connection
'''
class GCNGRU(torch.nn.Module):
    def __init__(
        self,
        in_channels: int,  
        periods: int, 
        batch_size:int, 
        improved: bool = False,
        cached: bool = False,
        add_self_loops: bool = True):
        super().__init__()

        self.in_channels = in_channels  # 2
        self.periods = periods # 12
        self.improved = improved
        self.cached = cached
        self.add_self_loops = add_self_loops
        self.batch_size = batch_size
        self._setup_layers()

    def _setup_layers(self):
        self.gcns = KLayerGCNConv( K=3,
                                   in_channels=self.in_channels,
                                   out_channels=128,
                                   node_dim=1,
                                   improved=self.improved,
                                   cached=self.cached,
                                   add_self_loops=self.add_self_loops,
                                  )
#         self.gcn1 = GCNConv(
#             in_channels=self.in_channels,
#             out_channels=128,
#             improved=self.improved,
#             cached=self.cached,
#             add_self_loops=self.add_self_loops,
#         )
#         self.gcn2 = GCNConv(
#             in_channels=128,
#             out_channels=128,
#             improved=self.improved,
#             cached=self.cached,
#             add_self_loops=self.add_self_loops,
#         )
#         self.gcn3 = GCNConv(
#             in_channels=128,
#             out_channels=128,
#             improved=self.improved,
#             cached=self.cached,
#             add_self_loops=self.add_self_loops,
#         )
        self.gru = torch.nn.GRU(128,64,2,batch_first=True)
        self.fc = torch.nn.Linear(64, self.periods)

    def forward(self, 
                X: torch.FloatTensor,
                edge_index: torch.LongTensor, 
                edge_weight: torch.FloatTensor = None,
               ) -> torch.FloatTensor:
        gru_in = torch.zeros(X.shape[0],X.shape[1],self.periods,128).to(X.device) # (B,N,T,F_out_GCN)
        for period in range(self.periods):
            gcn_out = self.gcns(X[:,:,:,period], edge_index, edge_weight)                 
#             gcn_out = self.gcn1(X[:, :, :, period], edge_index, edge_weight) # (B, N, Fout)
#             gcn_out = self.gcn2(gcn_out, edge_index, edge_weight) # (B, N, Fout)
#             gcn_out = self.gcn3(gcn_out, edge_index, edge_weight) # (B, N, Fout)
            gru_in[:,:,period,:] = gcn_out
        gru_in = gru_in.flatten(start_dim=0, end_dim=1) # (B*N, T, F_out_GCN)
        gru_out, _ = self.gru(gru_in) # (B*N,T,H)
        out = self.fc(gru_out[:,-1,:]) # (B*N, Tout)
#         out = F.leaky_relu(out)
        out = out.view(X.shape[0], X.shape[1], self.periods, -1) # (B,N,Tout,1)
        return out.squeeze(dim=3) # (B,N,T)
    
class A3TGCN_2(torch.nn.Module):
    def __init__(self, node_features, periods, batch_size):
        super().__init__()
        # Attention Temporal Graph Convolutional Cell
        self.tgnn = A3TGCN2(in_channels=node_features,  out_channels=64, periods=periods,batch_size=batch_size) # node_features=2, periods=12
        # Equals single-shot prediction
        self.fc = torch.nn.Linear(64, periods)

    def forward(self, x, edge_index):
        """
        x = Node features for T time steps
        edge_index = Graph edge indices
        """
        h = self.tgnn(x, edge_index) # x [b, 207, 2, 12]  returns h [b, 207, 12]
        h = self.fc(h)
        return h

class TGCN_2(torch.nn.Module): 
    r"""An implementation THAT SUPPORTS BATCHES of the Attention Temporal Graph Convolutional Cell.
    For details see this paper: `"A3T-GCN: Attention Temporal Graph Convolutional
    Network for Traffic Forecasting." <https://arxiv.org/abs/2006.11583>`_

    Args:
        in_channels (int): Number of input features.
        out_channels (int): Number of output features.
        periods (int): Number of time periods.
        improved (bool): Stronger self loops (default :obj:`False`).
        cached (bool): Caching the message weights (default :obj:`False`).
        add_self_loops (bool): Adding self-loops for smoothing (default :obj:`True`).
    """

    def __init__(self, node_features, periods, batch_size,
            improved: bool = False,
            cached: bool = False,
            add_self_loops: bool = True):
        super().__init__()
        self.tgnn = TGCN2(
            in_channels=node_features,
            out_channels=64,  
            batch_size=batch_size,
            improved=improved,
            cached=cached, 
            add_self_loops=add_self_loops)
        # Equals single-shot prediction
        self.fc = torch.nn.Linear(64, periods)
        self.periods = periods

    def forward( 
        self, 
        X: torch.FloatTensor,
        edge_index: torch.LongTensor, 
        edge_weight: torch.FloatTensor = None,
        H: torch.FloatTensor = None
    ) -> torch.FloatTensor:
        for period in range(self.periods):

            out = self.tgnn( X[:, :, :, period], edge_index, edge_weight, H) #([B, N, Fout]
        return self.fc(out)