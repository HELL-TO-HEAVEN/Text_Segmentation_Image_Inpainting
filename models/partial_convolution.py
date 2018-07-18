# Two types:
# 1. "Hard" gated : use 1/0 to update mask.  Image Inpainting for Irregular Holes Using Partial Convolutions
# 2. "Soft" gated : use sigmoid to update both feature & mask  Free-Form Image Inpainting with Gated Convolution

import torch
from torch import nn
from torch.nn import functional as F
from torch.nn.functional import avg_pool2d, upsample

from .BaseModels import BaseModule


class PartialConv(BaseModule):
    # reference:Image Inpainting for Irregular Holes Using Partial Convolutions
    # http://masc.cs.gmu.edu/wiki/partialconv/show?time=2018-05-24+21%3A41%3A10
    # https://github.com/naoto0804/pytorch-inpainting-with-partial-conv/blob/master/net.py
    # https://github.com/SeitaroShinagawa/chainer-partial_convolution_image_inpainting/blob/master/common/net.py
    # mask is binary, 0 is masked point, 1 is not
    def __init__(self, in_channels, out_channels, kernel_size, stride=1,
                 padding=0, dilation=1, groups=1, bias=True):
        super(PartialConv, self).__init__()
        self.feature_conv = nn.Conv2d(in_channels, out_channels, kernel_size, stride,
                                      padding, dilation, groups, bias)

        self.mask_conv = nn.Conv2d(in_channels, out_channels, kernel_size, stride,
                                   padding, dilation, groups, bias)
        torch.nn.init.constant(self.mask_conv.weight, 1.0)
        torch.nn.init.constant(self.mask_conv.bias, 0.0)
        for param in self.mask_conv.parameters():
            param.requires_grad = False

    def forward(self, args):
        x, mask = args
        output = self.feature_conv(x * mask)
        # memory efficient
        output_bias = self.feature_conv.bias.view(1, -1, 1, 1).expand_as(output)

        output_mask = self.mask_conv(mask)  # mask sums

        update_holes = output_mask != 0
        keep_holes = output_mask == 0
        output[update_holes] = (output[update_holes] - output_bias[update_holes]) \
                               / output_mask[update_holes] + output_bias[[update_holes]]

        output[keep_holes] = 0

        output_mask[update_holes] = 1.0
        output_mask[keep_holes] = 0.0
        return (output, output_mask)


class DoubleAvdPool(nn.AvgPool2d):
    def __init__(self, kernel_size):
        super(DoubleAvdPool, self).__init__(kernel_size=kernel_size)
        self.kernel_size = kernel_size

    def forward(self, args):
        type(args)
        return tuple(map(lambda x: avg_pool2d(x, kernel_size=self.kernel_size), args))


class DoubleUpSample(nn.Upsample):
    def __init__(self, scale_factor, mode):
        super(DoubleUpSample, self).__init__(scale_factor=scale_factor, mode=mode)
        self.scale_factor = scale_factor
        self.mode = mode

    def forward(self, args):
        return tuple(map(lambda x: upsample(x, scale_factor=self.scale_factor, mode=self.mode), args))


class DoubleActivation(nn.Module):
    def __init__(self, activation):
        super(DoubleActivation, self).__init__()
        self.activation = activation

    def forward(self, args):
        x, mask = args
        return self.activation(x), mask


class DoubleNorm(nn.Module):
    def __init__(self, norm):
        super(DoubleNorm, self).__init__()
        self.norm = norm

    def forward(self, args):
        x, mask = args
        return self.norm(x), mask


def partial_conv_block(in_channels, out_channels, kernel_size, stride=1,
                       padding=0, dilation=1, groups=1, bias=True, BN=True, activation=None):
    m = [PartialConv(in_channels, out_channels, kernel_size, stride,
                     padding, dilation, groups, bias)]
    if BN:
        m.append(DoubleNorm(nn.BatchNorm2d(out_channels)))
    if activation:
        m.append(DoubleActivation(activation))
    return m


class PartialGatedConv(BaseModule):
    # mask is binary, 0 is masked point, 1 is not
    # https://github.com/JiahuiYu/generative_inpainting/issues/62
    def __init__(self, in_channels, out_channels, kernel_size, stride=1,
                 padding=0, dilation=1, groups=1, bias=True, activation=nn.SELU()):
        super(PartialGatedConv, self).__init__()
        assert out_channels % 2 == 0
        self.feature_conv = nn.Conv2d(in_channels, out_channels, kernel_size, stride,
                                      padding, dilation, groups, bias)
        self.act_fn = activation

    def forward(self, x):
        output = self.feature_conv(x)
        feature, gate = output.chunk(2, dim=1)
        return self.act_fn(feature) * F.sigmoid(gate)


def partial_gated_conv_block(in_channels, out_channels, kernel_size, stride=1,
                             padding=0, dilation=1, groups=1, bias=True, BN=False, activation=nn.SELU()):
    m = [PartialGatedConv(in_channels, out_channels, kernel_size, stride,
                          padding, dilation, groups, bias, activation)]
    if BN:
        m.append(nn.BatchNorm2d(out_channels))

    return m

