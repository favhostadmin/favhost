from rest_framework import serializers
from .models import *

class AmenitiesSerializer(serializers.Serializer):
    class Meta:
        model = Amenities
        fields = ['id','icon','name']


