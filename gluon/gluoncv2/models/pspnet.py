"""
    PSPNet, implemented in Gluon.
    Original paper: 'Pyramid Scene Parsing Network,' https://arxiv.org/abs/1612.01105.
"""

__all__ = ['PSPNet', 'pspnet_resnet50_voc', 'pspnet_resnet101_voc', 'pspnet_resnet50_coco', 'pspnet_resnet101_coco',
           'pspnet_resnet50_ade20k', 'pspnet_resnet101_ade20k', 'pspnet_resnet50_sityscapes',
           'pspnet_resnet101_sityscapes']

import os
from mxnet import cpu
from mxnet.gluon import nn, HybridBlock
from mxnet.gluon.contrib.nn import HybridConcurrent, Identity
from .common import conv1x1, conv1x1_block, conv3x3_block
from .resnetd import resnetd50b, resnetd101b


class PSPFinalBlock(HybridBlock):
    """
    PSPNet final block.

    Parameters:
    ----------
    in_channels : int
        Number of input channels.
    out_channels : int
        Number of output channels.
    out_size : tuple of 2 int
        Spatial size of the output image for the bilinear upsampling operation.
    bottleneck_factor : int, default 4
        Bottleneck factor.
    """
    def __init__(self,
                 in_channels,
                 out_channels,
                 out_size,
                 bottleneck_factor=4,
                 **kwargs):
        super(PSPFinalBlock, self).__init__(**kwargs)
        self.out_size = out_size
        assert (in_channels % bottleneck_factor == 0)
        mid_channels = in_channels // bottleneck_factor

        with self.name_scope():
            self.conv1 = conv3x3_block(
                in_channels=in_channels,
                out_channels=mid_channels)
            self.dropout = nn.Dropout(rate=0.1)
            self.conv2 = conv1x1(
                in_channels=mid_channels,
                out_channels=out_channels,
                use_bias=True)

    def hybrid_forward(self, F, x):
        x = self.conv1(x)
        x = self.dropout(x)
        x = self.conv2(x)
        x = F.contrib.BilinearResize2D(x, height=self.out_size[0], width=self.out_size[1])
        return x


class PyramidPoolingBranch(HybridBlock):
    """
    Pyramid Pooling branch.

    Parameters:
    ----------
    in_channels : int
        Number of input channels.
    out_channels : int
        Number of output channels.
    output_size : int
        Target output size of the image.
    out_size : tuple of 2 int
        Spatial size of output image for the bilinear upsampling operation.
    """
    def __init__(self,
                 in_channels,
                 out_channels,
                 output_size,
                 out_size,
                 **kwargs):
        super(PyramidPoolingBranch, self).__init__(**kwargs)
        self.output_size = output_size
        self.out_size = out_size

        with self.name_scope():
            self.conv = conv1x1_block(
                in_channels=in_channels,
                out_channels=out_channels)

    def hybrid_forward(self, F, x):
        x = F.contrib.AdaptiveAvgPooling2D(x, output_size=self.output_size)
        x = self.conv(x)
        x = F.contrib.BilinearResize2D(x, height=self.out_size[0], width=self.out_size[1])
        return x


class PyramidPooling(HybridBlock):
    """
    Pyramid Pooling module.

    Parameters:
    ----------
    in_channels : int
        Number of input channels.
    in_size : tuple of 2 int
        Spatial size of the input tensor for the bilinear upsampling operation.
    """
    def __init__(self,
                 in_channels,
                 in_size,
                 **kwargs):
        super(PyramidPooling, self).__init__(**kwargs)
        output_sizes = [1, 2, 3, 6]
        assert (len(output_sizes) == 4)
        assert (in_channels % 4 == 0)
        mid_channels = in_channels // 4

        with self.name_scope():
            self.branches = HybridConcurrent(axis=1, prefix='')
            self.branches.add(Identity())
            for output_size in output_sizes:
                self.branches.add(PyramidPoolingBranch(
                    in_channels=in_channels,
                    out_channels=mid_channels,
                    output_size=output_size,
                    out_size=in_size))

    def hybrid_forward(self, F, x):
        x = self.branches(x)
        return x


class PSPNet(HybridBlock):
    """
    PSPNet model from 'Pyramid Scene Parsing Network,' https://arxiv.org/abs/1612.01105.

    Parameters:
    ----------
    backbone : nn.Sequential
        Feature extractor.
    backbone_out_channels : int, default 2048
        Number of output channels form feature extractor.
    aux : bool, default False
        Whether to output an auxiliary result.
    in_channels : int, default 3
        Number of input channels.
    in_size : tuple of two ints, default (480, 480)
        Spatial size of the expected input image.
    classes : int, default 21
        Number of segmentation classes.
    """
    def __init__(self,
                 backbone,
                 backbone_out_channels=2048,
                 aux=False,
                 in_channels=3,
                 in_size=(480, 480),
                 classes=21,
                 **kwargs):
        super(PSPNet, self).__init__(**kwargs)
        assert (in_channels > 0)
        assert ((in_size[0] % 8 == 0) and (in_size[1] % 8 == 0))
        self.in_size = in_size
        self.classes = classes
        self.aux = aux

        with self.name_scope():
            self.backbone = backbone
            self.pool = PyramidPooling(
                in_channels=backbone_out_channels,
                in_size=(self.in_size[0] // 8, self.in_size[1] // 8))
            pool_out_channels = 2 * backbone_out_channels
            self.final_block = PSPFinalBlock(
                in_channels=pool_out_channels,
                out_channels=classes,
                out_size=in_size,
                bottleneck_factor=8)
            if self.aux:
                aux_out_channels = backbone_out_channels // 2
                self.aux_block = PSPFinalBlock(
                    in_channels=aux_out_channels,
                    out_channels=classes,
                    out_size=in_size,
                    bottleneck_factor=4)

    def hybrid_forward(self, F, x):
        x, y = self.backbone(x)
        x = self.pool(x)
        x = self.final_block(x)
        if self.aux:
            y = self.aux_block(y)
            return x, y
        else:
            return x


def get_pspnet(backbone,
               classes,
               model_name=None,
               pretrained=False,
               ctx=cpu(),
               root=os.path.join('~', '.mxnet', 'models'),
               **kwargs):
    """
    Create PSPNet model with specific parameters.

    Parameters:
    ----------
    backbone : nn.Sequential
        Feature extractor.
    classes : int
        Number of segmentation classes.
    model_name : str or None, default None
        Model name for loading pretrained model.
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    ctx : Context, default CPU
        The context in which to load the pretrained weights.
    root : str, default '~/.mxnet/models'
        Location for keeping the model parameters.
    """

    net = PSPNet(
        backbone=backbone,
        classes=classes,
        **kwargs)

    if pretrained:
        if (model_name is None) or (not model_name):
            raise ValueError("Parameter `model_name` should be properly initialized for loading pretrained model.")
        from .model_store import get_model_file
        net.load_parameters(
            filename=get_model_file(
                model_name=model_name,
                local_model_store_dir_path=root),
            ctx=ctx)

    return net


def pspnet_resnet50_voc(pretrained_backbone=False, classes=21, **kwargs):
    """
    PSPNet model on the base of ResNet-50 for Pascal VOC from 'Pyramid Scene Parsing Network,'
    https://arxiv.org/abs/1612.01105.

    Parameters:
    ----------
    pretrained_backbone : bool, default False
        Whether to load the pretrained weights for feature extractor.
    classes : int, default 21
        Number of segmentation classes.
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    ctx : Context, default CPU
        The context in which to load the pretrained weights.
    root : str, default '~/.mxnet/models'
        Location for keeping the model parameters.
    """
    backbone = resnetd50b(pretrained=pretrained_backbone, ordinary_init=False, multi_output=True).features[:-1]
    return get_pspnet(backbone=backbone, classes=classes, aux=True, model_name="pspnet_resnet50_voc", **kwargs)


def pspnet_resnet101_voc(pretrained_backbone=False, classes=21, **kwargs):
    """
    PSPNet model on the base of ResNet-101 for Pascal VOC from 'Pyramid Scene Parsing Network,'
    https://arxiv.org/abs/1612.01105.

    Parameters:
    ----------
    pretrained_backbone : bool, default False
        Whether to load the pretrained weights for feature extractor.
    classes : int, default 21
        Number of segmentation classes.
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    ctx : Context, default CPU
        The context in which to load the pretrained weights.
    root : str, default '~/.mxnet/models'
        Location for keeping the model parameters.
    """
    backbone = resnetd101b(pretrained=pretrained_backbone, ordinary_init=False, multi_output=True).features[:-1]
    return get_pspnet(backbone=backbone, classes=classes, aux=True, model_name="pspnet_resnet101_voc", **kwargs)


def pspnet_resnet50_coco(pretrained_backbone=False, classes=21, **kwargs):
    """
    PSPNet model on the base of ResNet-50 for COCO from 'Pyramid Scene Parsing Network,'
    https://arxiv.org/abs/1612.01105.

    Parameters:
    ----------
    pretrained_backbone : bool, default False
        Whether to load the pretrained weights for feature extractor.
    classes : int, default 21
        Number of segmentation classes.
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    ctx : Context, default CPU
        The context in which to load the pretrained weights.
    root : str, default '~/.mxnet/models'
        Location for keeping the model parameters.
    """
    backbone = resnetd50b(pretrained=pretrained_backbone, ordinary_init=False, multi_output=True).features[:-1]
    return get_pspnet(backbone=backbone, classes=classes, aux=True, model_name="pspnet_resnet50_mscoco", **kwargs)


def pspnet_resnet101_coco(pretrained_backbone=False, classes=21, **kwargs):
    """
    PSPNet model on the base of ResNet-101 for COCO from 'Pyramid Scene Parsing Network,'
    https://arxiv.org/abs/1612.01105.

    Parameters:
    ----------
    pretrained_backbone : bool, default False
        Whether to load the pretrained weights for feature extractor.
    classes : int, default 21
        Number of segmentation classes.
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    ctx : Context, default CPU
        The context in which to load the pretrained weights.
    root : str, default '~/.mxnet/models'
        Location for keeping the model parameters.
    """
    backbone = resnetd101b(pretrained=pretrained_backbone, ordinary_init=False, multi_output=True).features[:-1]
    return get_pspnet(backbone=backbone, classes=classes, aux=True, model_name="pspnet_resnet101_mscoco", **kwargs)


def pspnet_resnet50_ade20k(pretrained_backbone=False, classes=150, **kwargs):
    """
    PSPNet model on the base of ResNet-50 for ADE20K from 'Pyramid Scene Parsing Network,'
    https://arxiv.org/abs/1612.01105.

    Parameters:
    ----------
    pretrained_backbone : bool, default False
        Whether to load the pretrained weights for feature extractor.
    classes : int, default 150
        Number of segmentation classes.
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    ctx : Context, default CPU
        The context in which to load the pretrained weights.
    root : str, default '~/.mxnet/models'
        Location for keeping the model parameters.
    """
    backbone = resnetd50b(pretrained=pretrained_backbone, ordinary_init=False, multi_output=True).features[:-1]
    return get_pspnet(backbone=backbone, classes=classes, aux=True, model_name="pspnet_resnet50_ade20k", **kwargs)


def pspnet_resnet101_ade20k(pretrained_backbone=False, classes=150, **kwargs):
    """
    PSPNet model on the base of ResNet-101 for ADE20K from 'Pyramid Scene Parsing Network,'
    https://arxiv.org/abs/1612.01105.

    Parameters:
    ----------
    pretrained_backbone : bool, default False
        Whether to load the pretrained weights for feature extractor.
    classes : int, default 150
        Number of segmentation classes.
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    ctx : Context, default CPU
        The context in which to load the pretrained weights.
    root : str, default '~/.mxnet/models'
        Location for keeping the model parameters.
    """
    backbone = resnetd101b(pretrained=pretrained_backbone, ordinary_init=False, multi_output=True).features[:-1]
    return get_pspnet(backbone=backbone, classes=classes, aux=True, model_name="pspnet_resnet50_ade20k", **kwargs)


def pspnet_resnet50_sityscapes(pretrained_backbone=False, classes=19, **kwargs):
    """
    PSPNet model on the base of ResNet-50 for Cityscapes from 'Pyramid Scene Parsing Network,'
    https://arxiv.org/abs/1612.01105.

    Parameters:
    ----------
    pretrained_backbone : bool, default False
        Whether to load the pretrained weights for feature extractor.
    classes : int, default 19
        Number of segmentation classes.
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    ctx : Context, default CPU
        The context in which to load the pretrained weights.
    root : str, default '~/.mxnet/models'
        Location for keeping the model parameters.
    """
    backbone = resnetd50b(pretrained=pretrained_backbone, ordinary_init=False, multi_output=True).features[:-1]
    return get_pspnet(backbone=backbone, classes=classes, aux=True, model_name="pspnet_resnet50_sityscapes", **kwargs)


def pspnet_resnet101_sityscapes(pretrained_backbone=False, classes=19, **kwargs):
    """
    PSPNet model on the base of ResNet-101 for Cityscapes from 'Pyramid Scene Parsing Network,'
    https://arxiv.org/abs/1612.01105.

    Parameters:
    ----------
    pretrained_backbone : bool, default False
        Whether to load the pretrained weights for feature extractor.
    classes : int, default 19
        Number of segmentation classes.
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    ctx : Context, default CPU
        The context in which to load the pretrained weights.
    root : str, default '~/.mxnet/models'
        Location for keeping the model parameters.
    """
    backbone = resnetd101b(pretrained=pretrained_backbone, ordinary_init=False, multi_output=True).features[:-1]
    return get_pspnet(backbone=backbone, classes=classes, aux=True, model_name="pspnet_resnet101_sityscapes", **kwargs)


def _test():
    import numpy as np
    import mxnet as mx

    in_size = (480, 480)
    aux = False
    pretrained = False

    models = [
        (pspnet_resnet50_voc, 21),
        (pspnet_resnet101_voc, 21),
        (pspnet_resnet50_coco, 21),
        (pspnet_resnet101_coco, 21),
        (pspnet_resnet50_ade20k, 150),
        (pspnet_resnet101_ade20k, 150),
        (pspnet_resnet50_sityscapes, 19),
        (pspnet_resnet101_sityscapes, 19),
    ]

    for model, classes in models:

        net = model(pretrained=pretrained, in_size=in_size, aux=aux)

        ctx = mx.cpu()
        if not pretrained:
            net.initialize(ctx=ctx)

        # net.hybridize()
        net_params = net.collect_params()
        weight_count = 0
        for param in net_params.values():
            if (param.shape is None) or (not param._differentiable):
                continue
            weight_count += np.prod(param.shape)
        print("m={}, {}".format(model.__name__, weight_count))
        if aux:
            assert (model != pspnet_resnet50_voc or weight_count == 49081536)
            assert (model != pspnet_resnet101_voc or weight_count == 68073664)
            assert (model != pspnet_resnet50_coco or weight_count == 49081536)
            assert (model != pspnet_resnet101_coco or weight_count == 68073664)
            assert (model != pspnet_resnet50_ade20k or weight_count == 49180608)
            assert (model != pspnet_resnet101_ade20k or weight_count == 68172736)
            assert (model != pspnet_resnet50_sityscapes or weight_count == 49080000)
            assert (model != pspnet_resnet101_sityscapes or weight_count == 68072128)
        else:
            assert (model != pspnet_resnet50_voc or weight_count == 46716352)
            assert (model != pspnet_resnet101_voc or weight_count == 65708480)
            assert (model != pspnet_resnet50_coco or weight_count == 46716352)
            assert (model != pspnet_resnet101_coco or weight_count == 65708480)
            assert (model != pspnet_resnet50_ade20k or weight_count == 46782400)
            assert (model != pspnet_resnet101_ade20k or weight_count == 65774528)
            assert (model != pspnet_resnet50_sityscapes or weight_count == 46715328)
            assert (model != pspnet_resnet101_sityscapes or weight_count == 65707456)

        x = mx.nd.zeros((1, 3, in_size[0], in_size[1]), ctx=ctx)
        ys = net(x)
        y = ys[0] if aux else ys
        assert ((y.shape[0] == x.shape[0]) and (y.shape[1] == classes) and (y.shape[2] == x.shape[2]) and
                (y.shape[3] == x.shape[3]))


if __name__ == "__main__":
    _test()
